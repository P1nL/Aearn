import json
import uuid
from collections.abc import Mapping

import psycopg
import pytest
from fastapi.testclient import TestClient

import app.routes.plans as plans_route
import app.routes.reviews as reviews_route
from app.agents.learning.learning_public_output import learning_public_output_json
from app.core.config import Settings, get_settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.main import app
from app.services.conversations import learning_conversation
from app.services.curriculum.dynamic_plan_generation import DynamicPlanDraftResult
from app.services.curriculum.plan_generator import build_plan_draft
from app.services.repositories import learning_session_repository, review_repository, review_seed_bank
from app.services.repositories.learner_profile import get_learner_profile
from app.services.repositories.review_scheduler import apply_attempt_review_update
from aearn_worker.review_seed_bank_core import (
    GENERATOR_VERSION,
    ReviewSeedBankValidationError,
    validate_review_seed_bank as validate_review_seed_bank_payload,
)


def _database_available() -> bool:
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=2) as conn:
            conn.execute("select 1")
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not _database_available(),
    reason="PostgreSQL is not available; run aearn infra compose for DB smoke tests.",
)


@pytest.fixture()
def client() -> TestClient:
    bootstrap_database()
    return TestClient(app)


@pytest.fixture(autouse=True)
def disable_review_coach_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeLearningConversationClient:
        model = "fake-teaching-model"

        def complete_text_stream(self, messages, *, temperature=None):  # type: ignore[no-untyped-def]
            del messages, temperature
            return ["我会生成当前练习，并保持讲解聚焦在可见题面。"]

        def complete_structured_text_stream(self, messages, *, output_type, temperature=None):  # type: ignore[no-untyped-def]
            del output_type
            public_message = "".join(self.complete_text_stream(messages, temperature=temperature))
            return [learning_public_output_json(public_message)]

    def fake_concept_intro(*args, **kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        del args, kwargs
        return {
            "summary": "事件绑定会把一次用户动作连接到回调函数，状态变量决定多次动作之间是否共享记忆。",
            "example": {
                "title": "计数按钮",
                "body": "count 放在回调外面时，每次点击都会基于同一个 count 继续累加。",
                "takeaway": "先看状态放在哪里，再看事件什么时候触发回调。",
            },
            "check": {
                "type": "single_choice",
                "question": "如果 count 写在点击回调里面，每次点击最可能发生什么？",
                "options": [
                    {"id": "A", "text": "每次点击都重新从初始值开始。"},
                    {"id": "B", "text": "每次点击都会复用上一次回调里的局部变量。"},
                    {"id": "C", "text": "事件监听器不会再触发。"},
                ],
                "expected_focus": "回调作用域与跨点击状态共享的关系",
            },
        }

    def fake_review_warmup_judgement(context) -> dict[str, object]:  # type: ignore[no-untyped-def]
        normalized = context.learner_answer.strip().lower()
        if not normalized or normalized in {"不太确定", "完全忘了", "不知道", "unclear", "not sure"}:
            result = "unclear"
        elif any(marker in normalized for marker in ("状态", "作用域", "返回", "stdout", "测试", "state", "scope", "return", "test")):
            result = "correct"
        else:
            result = "incorrect"
        return {
            "result": result,
            "confidence": "high",
            "feedback": {
                "correct": "回答覆盖了当前知识点的核心关系。",
                "incorrect": "回答和当前知识点相关，但还缺少关键关系。",
                "unclear": "回答还不足以判断掌握程度，需要一次更窄的修正。",
            }[result],
            "generation_source": "llm",
            "generation_model": "fake-review-warmup-judge",
        }

    monkeypatch.setattr(learning_session_repository, "build_sdk_concept_intro", fake_concept_intro)
    monkeypatch.setattr(
        review_repository,
        "build_sdk_review_coach_response",
        lambda context: {
            "initial_agent_message": f"这次复习围绕 {context.knowledge_point_title}，先用变体题验证你是否真的能接管这类代码。",
            "variant_reason": "本次不重复聊天问答，改用同构代码练习检查是否能独立验证。",
            "generation_source": "llm",
            "generation_model": "fake-review-coach",
        },
    )
    monkeypatch.setattr(
        review_repository,
        "build_sdk_review_warmup_judgement_response",
        fake_review_warmup_judgement,
    )
    monkeypatch.setattr(plans_route, "build_dynamic_plan_draft", _fake_dynamic_plan_draft)
    monkeypatch.setattr(
        learning_session_repository,
        "build_sdk_explanation_check_response",
        lambda *args, **kwargs: {
            "result": "passed",
            "score": 2,
            "score_breakdown": {"explanation_check": 2},
            "follow_up_required": False,
            "feedback": "解释覆盖了状态作用域和连续点击行为。",
            "next_action": "submit",
        },
    )
    monkeypatch.setattr(
        learning_conversation,
        "get_settings",
        lambda: Settings(
            llm_type="openai",
            openai_api_key="test-key",
            openai_base_url="https://provider.example",
            openai_model="fake-teaching-model",
        ),
    )
    monkeypatch.setattr(
        learning_conversation,
        "AgentsSDKLearningConversationClient",
        lambda settings, **kwargs: FakeLearningConversationClient(),
    )


def _fake_dynamic_plan_draft(payload, user, course, **kwargs):  # type: ignore[no-untyped-def]
    del kwargs
    plan_draft = build_plan_draft(payload, user, course)
    return DynamicPlanDraftResult(
        plan_draft=plan_draft,
        agent_notes=[plan_draft.runtime_boundary.notice, "Test fake dynamic plan."],
    )


def _fake_model_review_seeds(context: Mapping[str, object]) -> list[dict[str, object]]:
    runtime_profile = context.get("runtime_profile")
    runtime_profile = runtime_profile if isinstance(runtime_profile, Mapping) else {}
    language = str(runtime_profile.get("language") or "javascript")
    runtime_tier = str(runtime_profile.get("runtime_tier") or "browser_preview")
    knowledge_point_id = str(context["knowledge_point_id"])
    title = str(context.get("knowledge_point_title") or "Review concept")
    supported = context.get("supported_exercise_types")
    supported_types = [str(item) for item in supported] if isinstance(supported, list) else ["code_blank"]
    preferred = ["code_blank", "fix_bug", "review_ai_patch", "explain_code", "implement_function"]
    type_cycle = [exercise_type for exercise_type in preferred if exercise_type in supported_types] or [supported_types[0]]
    target_seed_count = int(context.get("target_seed_count") or 10)

    seeds: list[dict[str, object]] = []
    for index in range(target_seed_count):
        exercise_type = type_cycle[index % len(type_cycle)]
        if exercise_type == "review_ai_patch":
            seed = _fake_model_review_patch_seed(
                knowledge_point_id=knowledge_point_id,
                title=title,
                language=language,
                runtime_tier=runtime_tier,
                index=index,
            )
        else:
            seed = _fake_model_practice_seed(
                knowledge_point_id=knowledge_point_id,
                title=title,
                language=language,
                runtime_tier=runtime_tier,
                exercise_type=exercise_type,
                index=index,
            )
        seeds.append(seed)
    return seeds


def _fake_model_practice_seed(
    *,
    knowledge_point_id: str,
    title: str,
    language: str,
    runtime_tier: str,
    exercise_type: str,
    index: int,
) -> dict[str, object]:
    seed_id = f"fake_model_{exercise_type}_{index + 1:02d}"
    if language == "python":
        starter_code = "def summarize_scores(scores):\n    total = sum(scores)\n    return __BLANK_1__\n"
        required_patterns = ["return total"]
        code_blanks = [
            {
                "blank_key": "blank_1",
                "placeholder": "total",
                "expected_concept": "Return the computed total so callers can use it.",
                "acceptable_patterns_json": [{"type": "literal", "value": "total"}],
                "is_core": True,
                "order_index": 0,
            }
        ]
        test_cases = [_fake_visible_case({"scores": [2, 3, 4]}, {"return": 9})]
    else:
        starter_code = (
            "const button = document.querySelector(\"#counter-button\");\n"
            "const output = document.querySelector(\"#counter-output\");\n"
            "let count = 0;\n\n"
            "button.__BLANK_1__(\"click\", () => {\n"
            "  __BLANK_2__;\n"
            "  output.textContent = String(count);\n"
            "});\n"
        )
        required_patterns = ["addEventListener", "count += 1", "output.textContent"]
        code_blanks = [
            {
                "blank_key": "blank_1",
                "placeholder": "addEventListener",
                "expected_concept": "Bind the click listener to the button.",
                "acceptable_patterns_json": [{"type": "literal", "value": "addEventListener"}],
                "is_core": True,
                "order_index": 0,
            },
            {
                "blank_key": "blank_2",
                "placeholder": "count += 1",
                "expected_concept": "Increment the shared counter inside the event callback.",
                "acceptable_patterns_json": [{"type": "literal", "value": "count += 1"}],
                "is_core": True,
                "order_index": 1,
            },
        ]
        test_cases = [
            _fake_visible_case({"event": "click"}, {"textContent": "1"}),
            _fake_preview_case({"selector": "#counter-output"}, {"textContent": "1"}, order_index=1),
        ]
    return {
        "id": seed_id,
        "exercise_type": exercise_type,
        "difficulty": 2 + (index % 3),
        "capability": _fake_candidate_capability(exercise_type, index=index),
        "target_misconception": f"model_context_gap_{index}",
        "focus_tags": [f"model_context_gap_{index}", "state", "evidence"],
        "recommended_for": {
            "recall_levels": ["fuzzy", "wrong", "skipped"],
            "weak_points": [f"model_context_gap_{index}"],
            "after_result": ["failed", "partial"],
        },
        "avoid_if": {
            "already_passed_focus_tags": [f"model_context_gap_{index}"],
            "recent_candidate_ids": [],
            "unsupported_runtime_tiers": [],
        },
        "knowledge_point_id": knowledge_point_id,
        "runtime_tier": runtime_tier,
        "title": f"{title}: model-generated {exercise_type}",
        "warmup_question": f"Before the model-generated variant {index + 1}, recall what state must stay observable.",
        "warmup_expected_focus": "State, return value, or evidence must match the visible behavior.",
        "warmup_keywords": ["state", "return", "evidence"],
        "review_focus": "Use the latest learner state to target the fragile concept.",
        "prompt_markdown": f"Model-generated review seed {index + 1}: complete the {exercise_type} task for **{title}**.",
        "starter_code": starter_code,
        "visible_test_policy": "visible_only",
        "requires_explanation": True,
        "metadata": {
            "required_patterns": required_patterns,
            "browser_rule_family": "js_event_flow" if language != "python" else "",
            "review_focus": "latest learner state",
            "selection_reason": f"Use {exercise_type} to test model context gap {index}.",
            "is_core": index % 2 == 0,
        },
        "code_blanks": code_blanks,
        "test_cases": test_cases,
    }


def _fake_model_review_patch_seed(
    *,
    knowledge_point_id: str,
    title: str,
    language: str,
    runtime_tier: str,
    index: int,
) -> dict[str, object]:
    if language == "python":
        original_code = "def summarize_scores(scores):\n    total = sum(scores)\n    return total\n"
        ai_diff = "-    return total\n+    print(total)\n+    return None"
        expected_risk = "The caller loses the function return value."
    else:
        original_code = (
            "let count = 0;\n"
            "button.addEventListener(\"click\", () => {\n"
            "  count += 1;\n"
            "  output.textContent = String(count);\n"
            "});\n"
        )
        ai_diff = "-let count = 0;\n button.addEventListener(\"click\", () => {\n+  let count = 0;\n   count += 1;"
        expected_risk = "The counter is recreated on every click, so repeated clicks do not accumulate."
    rubric = {
        "verdict_correctness": "0-2",
        "evidence_grounding": "0-2",
        "knowledge_point_alignment": "0-2",
        "actionability": "0-2",
    }
    return {
        "id": f"fake_model_review_ai_patch_{index + 1:02d}",
        "exercise_type": "review_ai_patch",
        "difficulty": 4,
        "capability": "transfer_or_review",
        "target_misconception": "review_patch_evidence",
        "focus_tags": ["review_patch_evidence", "ai_patch", "evidence"],
        "recommended_for": {
            "recall_levels": ["fuzzy", "wrong", "skipped"],
            "weak_points": ["review_patch_evidence"],
            "after_result": ["failed", "partial"],
        },
        "avoid_if": {
            "already_passed_focus_tags": ["review_patch_evidence"],
            "recent_candidate_ids": [],
            "unsupported_runtime_tiers": [],
        },
        "knowledge_point_id": knowledge_point_id,
        "runtime_tier": runtime_tier,
        "title": f"{title}: model-generated AI patch review",
        "warmup_question": "What evidence should you inspect before accepting an AI patch?",
        "warmup_expected_focus": "Use the requirement, diff, and visible behavior together.",
        "warmup_keywords": ["requirement", "diff", "evidence"],
        "review_focus": "Ground the verdict in the requirement and diff.",
        "prompt_markdown": f"Model-generated review seed {index + 1}: audit the AI patch for **{title}**.",
        "starter_code": original_code,
        "visible_test_policy": "visible_only",
        "requires_explanation": True,
        "metadata": {
            "requirement": "Keep the observable behavior and preserve the concept under review.",
            "original_code": original_code,
            "ai_diff": ai_diff,
            "review_focus": "Ground the verdict in requirement, diff, and behavior.",
            "expected_risk": expected_risk,
            "expected_verdict": "fail",
            "expected_next_action": "request_change",
            "rubric": rubric,
            "selection_reason": "Review AI patch evidence before trusting the generated change.",
            "is_core": True,
        },
        "rubric": rubric,
        "code_blanks": [],
        "test_cases": [],
    }


def _fake_visible_case(input_json: Mapping[str, object], expected_output_json: Mapping[str, object]) -> dict[str, object]:
    return {
        "case_type": "visible",
        "input_json": dict(input_json),
        "expected_output_json": dict(expected_output_json),
        "assertion_code": None,
        "weight": 1,
        "is_critical": True,
        "timeout_ms": 5000,
        "order_index": 0,
    }


def _fake_preview_case(
    input_json: Mapping[str, object],
    expected_output_json: Mapping[str, object],
    *,
    order_index: int,
) -> dict[str, object]:
    return {
        "case_type": "preview_assertion",
        "input_json": dict(input_json),
        "expected_output_json": dict(expected_output_json),
        "assertion_code": None,
        "weight": 1,
        "is_critical": False,
        "timeout_ms": 5000,
        "order_index": order_index,
    }


def _fake_candidate_capability(exercise_type: str, *, index: int) -> str:
    if exercise_type == "review_ai_patch":
        return "transfer_or_review"
    if exercise_type == "fix_bug":
        return "debugging"
    if exercise_type == "explain_code":
        return "concept_explanation"
    if exercise_type == "implement_function" and index % 2 == 1:
        return "transfer_or_review"
    return "basic_application"


def test_today_reviews_returns_empty_and_sorted_due_items(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    first_kp_id = plan["knowledge_points"][0]["id"]
    second_kp_id = plan["knowledge_points"][1]["id"]

    empty = client.get(f"/api/reviews/today?user_id={user['id']}")
    assert empty.status_code == 200
    assert empty.json()["items"] == []

    with connect() as conn:
        conn.execute(
            """
            UPDATE review_states
            SET card_state = 'review',
                due_at = now() - interval '20 minutes',
                last_fsrs_rating = 'Good',
                reps = 2
            WHERE knowledge_point_id = %s
            """,
            (first_kp_id,),
        )
        conn.execute(
            """
            UPDATE review_states
            SET card_state = 'review',
                due_at = now() - interval '10 minutes',
                last_fsrs_rating = 'Hard',
                reps = 1
            WHERE knowledge_point_id = %s
            """,
            (second_kp_id,),
        )
        conn.execute(
            """
            UPDATE knowledge_points
            SET status = 'reviewing'
            WHERE id IN (%s, %s)
            """,
            (first_kp_id, second_kp_id),
        )
        conn.commit()

    due = client.get(f"/api/reviews/today?user_id={user['id']}")
    assert due.status_code == 200
    body = due.json()
    assert [item["KnowledgePoint"]["id"] for item in body["items"][:2]] == [first_kp_id, second_kp_id]
    assert body["items"][0]["ReviewState"]["review_count"] == 2
    assert body["timezone"] == "Asia/Shanghai"


def test_review_start_requires_due_state_and_reuses_active_session(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]

    early = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert early.status_code == 409
    assert early.json()["error"]["code"] == "REVIEW_NOT_DUE"

    _mark_due(knowledge_point_id)

    created = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert created.status_code == 201
    created_body = created.json()
    assert created_body["session_type"] == "review"
    assert created_body["knowledge_point"]["id"] == knowledge_point_id
    assert created_body["review_exercise"]["knowledge_point_id"] == knowledge_point_id
    assert created_body["review_stage"] == "warmup"
    assert created_body["current_node"]["type"] == "warmup"
    assert created_body["current_node"]["stage"] == "warmup"
    assert created_body["current_node"]["target_count"] >= 3
    assert created_body["warmup"]["result"] == "pending"
    assert created_body["selected_seed_id"]
    assert created_body["seed_bank"]["status"] == "ready"
    assert created_body["seed_bank"]["generator_version"] == GENERATOR_VERSION
    assert created_body["review_stage_state"]["schema_version"] == "review_batch_v1"
    assert created_body["review_stage_state"]["batch"]["min_exercise_count"] == 3
    assert created_body["review_stage_state"]["batch"]["max_exercise_count"] == 6
    assert created_body["review_stage_state"]["batch"]["current_exercise_id"] == created_body["review_exercise"]["id"]
    assert created_body["review_stage_state"]["batch"]["current_candidate_id"] == created_body["selected_seed_id"]
    assert created_body["review_stage_state"]["pool"]["generator_version"] == GENERATOR_VERSION
    assert created_body["review_stage_state"]["exercise_plan"][0]["candidate_id"] == created_body["selected_seed_id"]
    assert created_body["review_stage_state"]["finalization"]["status"] == "pending"
    assert "模型生成复习题" in created_body["review_exercise"]["prompt_markdown"]
    assert created_body["review_exercise"]["metadata_json"]["seed_generator_version"] == GENERATOR_VERSION
    review_seed_metadata = created_body["review_exercise"]["metadata_json"]["review_seed"]
    assert review_seed_metadata["seed_bank_id"]
    assert review_seed_metadata["candidate_id"] == created_body["selected_seed_id"]
    assert review_seed_metadata["capability"] in {
        "basic_application",
        "concept_explanation",
        "debugging",
        "transfer_or_review",
    }
    assert review_seed_metadata["focus_tags"]
    assert review_seed_metadata["selection_reason"]
    assert created_body["variant_reason"]
    assert created_body["initial_agent_message"].startswith("这次复习围绕 ")

    replayed = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert replayed.status_code == 200
    replayed_body = replayed.json()
    assert replayed_body["session_id"] == created_body["session_id"]
    assert replayed_body["selected_seed_id"] == created_body["selected_seed_id"]
    assert replayed_body["warmup"] == created_body["warmup"]
    assert replayed_body["current_node"]["type"] == created_body["current_node"]["type"]
    assert replayed_body["review_stage_state"]["schema_version"] == "review_batch_v1"


def test_review_start_uses_sdk_review_coach_text_when_available(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id)

    monkeypatch.setattr(
        review_repository,
        "build_sdk_review_coach_response",
        lambda context: {
            "initial_agent_message": "先看状态变量的变体题，别急着提交。",
            "variant_reason": "上次薄弱点是 state_scope_error。",
            "coaching_text": "先对照上次错因再动手。",
            "generation_source": "llm",
            "generation_model": "sdk-review-model",
        },
    )

    created = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert created.status_code == 201
    created_body = created.json()
    assert created_body["initial_agent_message"] == "先看状态变量的变体题，别急着提交。"
    assert created_body["variant_reason"] == "上次薄弱点是 state_scope_error。"


def test_review_start_returns_model_unavailable_when_sdk_review_text_leaks_answer(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id)

    monkeypatch.setattr(
        review_repository,
        "build_sdk_review_coach_response",
        lambda context: {
            "initial_agent_message": "完整答案如下：直接把 count 放在回调内部。",
            "variant_reason": "失败来自 hidden_three_clicks。",
        },
    )

    created = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert created.status_code == 503
    body = created.json()
    assert body["error"]["code"] == "MODEL_UNAVAILABLE"


def test_review_start_returns_seed_bank_generation_failed_without_fallback(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id)

    def raise_generation_failure(context: Mapping[str, object]) -> None:
        del context
        return None

    monkeypatch.setattr(review_seed_bank, "build_model_review_seed_bank", raise_generation_failure)

    created = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert created.status_code == 503
    body = created.json()
    assert body["error"]["code"] == "REVIEW_SEED_BANK_GENERATION_FAILED"
    assert "review_exercise" not in body

    with connect() as conn:
        bank = conn.execute(
            """
            SELECT status, seed_count, failure_code
            FROM review_seed_banks
            WHERE user_id = %s AND knowledge_point_id = %s
            """,
            (user["id"], knowledge_point_id),
        ).fetchone()
    assert bank is not None
    assert bank["status"] == "failed"
    assert bank["seed_count"] == 0
    assert bank["failure_code"] == "REVIEW_SEED_BANK_GENERATION_FAILED"


def test_review_start_rejects_invalid_candidate_pool_without_fallback(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id)

    def invalid_candidate_pool(context: Mapping[str, object]) -> review_seed_bank.GeneratedReviewSeedBank:
        seeds = _fake_model_review_seeds(context)
        metadata = dict(seeds[0]["metadata"]) if isinstance(seeds[0].get("metadata"), Mapping) else {}
        metadata.pop("selection_reason", None)
        seeds[0]["metadata"] = metadata
        return review_seed_bank.GeneratedReviewSeedBank(
            content={"candidate_pool": {"candidates": seeds}},
            model="invalid-candidate-model",
        )

    monkeypatch.setattr(review_seed_bank, "build_model_review_seed_bank", invalid_candidate_pool)

    created = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert created.status_code == 503
    body = created.json()
    assert body["error"]["code"] == "REVIEW_SEED_BANK_GENERATION_FAILED"
    assert "review_exercise" not in body

    with connect() as conn:
        bank = conn.execute(
            """
            SELECT status, seed_count, failure_code
            FROM review_seed_banks
            WHERE user_id = %s AND knowledge_point_id = %s AND generator_version = %s
            """,
            (user["id"], knowledge_point_id, GENERATOR_VERSION),
        ).fetchone()
    assert bank is not None
    assert bank["status"] == "failed"
    assert bank["seed_count"] == 0
    assert bank["failure_code"] == "REVIEW_SEED_BANK_GENERATION_FAILED"


def test_review_candidate_pool_validation_enforces_schema_and_coverage() -> None:
    context = {
        "knowledge_point_id": "kp_candidate_pool",
        "knowledge_point_title": "Review concept",
        "runtime_profile": {"language": "javascript", "runtime_tier": "browser_preview"},
        "supported_exercise_types": ["code_blank", "fix_bug", "explain_code", "implement_function", "review_ai_patch"],
        "target_seed_count": 10,
    }
    seeds = _fake_model_review_seeds(context)
    quality_report = validate_review_seed_bank_payload(
        seeds,
        knowledge_point_id="kp_candidate_pool",
        high_risk=False,
        requires_review_ai_patch=True,
        supported_exercise_types=["code_blank", "fix_bug", "explain_code", "implement_function", "review_ai_patch"],
    )
    assert quality_report["candidate_count"] == 10
    assert quality_report["generator_version"] == GENERATOR_VERSION
    assert set(quality_report["capabilities"]) == {
        "basic_application",
        "concept_explanation",
        "debugging",
        "transfer_or_review",
    }
    assert quality_report["core_candidate_count"] > 0
    assert quality_report["focus_tag_count"] > 0

    too_few = seeds[:9]
    with pytest.raises(ReviewSeedBankValidationError, match="candidate count"):
        validate_review_seed_bank_payload(
            too_few,
            knowledge_point_id="kp_candidate_pool",
            high_risk=False,
            requires_review_ai_patch=True,
            supported_exercise_types=["code_blank", "fix_bug", "explain_code", "implement_function", "review_ai_patch"],
        )

    missing_metadata = [dict(seed) for seed in seeds]
    missing_metadata[0] = {**missing_metadata[0], "metadata": {"is_core": True}}
    with pytest.raises(ReviewSeedBankValidationError, match="selection_reason"):
        validate_review_seed_bank_payload(
            missing_metadata,
            knowledge_point_id="kp_candidate_pool",
            high_risk=False,
            requires_review_ai_patch=True,
            supported_exercise_types=["code_blank", "fix_bug", "explain_code", "implement_function", "review_ai_patch"],
        )

    leaked = [dict(seed) for seed in seeds]
    leaked[0] = {**leaked[0], "prompt_markdown": "This contains a hidden answer key."}
    with pytest.raises(ReviewSeedBankValidationError, match="unsafe"):
        validate_review_seed_bank_payload(
            leaked,
            knowledge_point_id="kp_candidate_pool",
            high_risk=False,
            requires_review_ai_patch=True,
            supported_exercise_types=["code_blank", "fix_bug", "explain_code", "implement_function", "review_ai_patch"],
        )


def test_review_seed_bank_prompt_requires_top_level_selection_metadata() -> None:
    context = {
        "knowledge_point_id": "kp_candidate_pool",
        "knowledge_point_title": "Review concept",
        "runtime_profile": {"language": "javascript", "runtime_tier": "browser_preview"},
        "supported_exercise_types": ["code_blank", "fix_bug", "explain_code", "implement_function", "review_ai_patch"],
        "target_seed_count": 10,
    }
    messages = review_seed_bank._review_seed_model_messages(context)  # type: ignore[attr-defined]
    user_payload = json.loads(messages[1]["content"])
    policy = user_payload["generation_policy"]
    candidate_schema = user_payload["response_shape"]["candidate_pool"]["candidates"][0]

    assert "top-level recommended_for" in policy
    assert "Do not move recommended_for or avoid_if inside metadata" in policy
    assert set(candidate_schema["recommended_for"]) == {"recall_levels", "weak_points", "after_result"}
    assert set(candidate_schema["avoid_if"]) == {
        "already_passed_focus_tags",
        "recent_candidate_ids",
        "unsupported_runtime_tiers",
    }
    assert "recommended_for" not in candidate_schema["metadata"]
    assert "avoid_if" not in candidate_schema["metadata"]


def test_review_seed_bank_model_context_adapts_to_learner_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    learning = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": knowledge_point_id,
        },
    )
    assert learning.status_code == 201
    exercise = _unlock_practice_exercise(client, learning.json())
    filled_blanks = _filled_blanks_for(exercise)
    run = client.post(
        f"/api/learning-sessions/{learning.json()['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": exercise["solution_reference"],
            "filled_blanks": filled_blanks,
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    assert run.status_code == 201
    submitted = client.post(
        f"/api/learning-sessions/{learning.json()['session_id']}/exercises/{exercise['id']}/submit",
        json={
            "attempt_id": run.json()["attempt_id"],
            "code": exercise["solution_reference"],
            "filled_blanks": filled_blanks,
            "submit_version": 1,
            "explanation": "状态变量放在回调外层，所以多次点击会共享同一个 count。",
            "hint_usage_count": 0,
            "error_count": 0,
        },
    )
    assert submitted.status_code == 200
    attempt_id = submitted.json()["attempt_id"]
    _mark_due(knowledge_point_id, reps=4)
    with connect() as conn:
        conn.execute(
            """
            UPDATE knowledge_points
            SET weak_points_json = %s::jsonb,
                mastery_score = 0.31
            WHERE id = %s
            """,
            (json.dumps(["state_scope_error", "test_evidence_gap"]), knowledge_point_id),
        )
        conn.execute(
            """
            UPDATE review_states
            SET last_attempt_id = %s,
                last_fsrs_rating = 'Again',
                reps = 4,
                lapses = 2
            WHERE knowledge_point_id = %s
            """,
            (attempt_id, knowledge_point_id),
        )
        conn.commit()

    captured: dict[str, object] = {}
    fake_generator = review_seed_bank.build_model_review_seed_bank

    def capture_generation_context(context: Mapping[str, object]):  # type: ignore[no-untyped-def]
        captured["context"] = context
        return fake_generator(context)

    monkeypatch.setattr(review_seed_bank, "build_model_review_seed_bank", capture_generation_context)

    started = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert started.status_code == 201
    started_body = started.json()
    context = captured["context"]
    assert isinstance(context, dict)
    learner_state = context["learner_state"]
    runtime_profile = context["runtime_profile"]
    assert isinstance(learner_state, dict)
    assert isinstance(runtime_profile, dict)
    assert learner_state["weak_points"] == ["state_scope_error", "test_evidence_gap"]
    assert learner_state["mastery_score"] == 0.31
    assert learner_state["last_fsrs_rating"] == "Again"
    assert learner_state["review_count"] == 4
    assert learner_state["lapse_count"] == 2
    assert learner_state["latest_attempt"]["attempt_id"] == attempt_id
    assert runtime_profile["language"] == "javascript"
    assert runtime_profile["runtime_tier"] == "browser_preview"
    assert context["target_seed_count"] == 12
    assert "模型生成" in started_body["review_exercise"]["title"]
    quality_report = started_body["seed_bank"]["quality_report"]
    assert quality_report["generation_source"] == "llm"
    assert quality_report["generation_model"] == "fake-review-seed-model"
    assert quality_report["candidate_count"] == 12
    assert set(quality_report["capabilities"]) == {
        "basic_application",
        "concept_explanation",
        "debugging",
        "transfer_or_review",
    }


def test_review_messages_replay_start_and_warmup_history(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id)

    created = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert created.status_code == 201
    review_session = created.json()
    session_id = review_session["session_id"]

    history = client.get(f"/api/reviews/{session_id}/messages", params={"user_id": user["id"]})
    assert history.status_code == 200
    messages = history.json()["messages"]
    assert [message["role"] for message in messages] == ["agent"]
    assert review_session["initial_agent_message"] not in messages[0]["content"]
    assert review_session["warmup"]["question"] in messages[0]["content"]

    replayed = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert replayed.status_code == 200
    replay_history = client.get(f"/api/reviews/{session_id}/messages", params={"user_id": user["id"]})
    assert replay_history.status_code == 200
    assert len(replay_history.json()["messages"]) == len(messages)

    warmup = client.post(
        f"/api/reviews/{session_id}/warmup-result",
        json={"user_id": user["id"], "action": "answer", "answer": "不太确定"},
    )
    assert warmup.status_code == 200
    after_warmup = client.get(f"/api/reviews/{session_id}/messages", params={"user_id": user["id"]})
    assert after_warmup.status_code == 200
    serialized = json.dumps(after_warmup.json(), ensure_ascii=False)
    assert "不太确定" in serialized
    assert warmup.json()["warmup"]["feedback"] in serialized
    assert "先做一次短修正" not in serialized
    assert "再修正一下" not in serialized
    assert "正式复习题" not in serialized

    legacy_feedback = "旧版独立复习提交反馈不应恢复成普通 Agent 消息。"
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO review_messages (review_session_id, role, content, client_message_id)
            VALUES (%s, 'agent', %s, %s)
            """,
            (session_id, legacy_feedback, f"review:{session_id}:exercise-result:legacy-attempt"),
        )
        conn.commit()
    filtered_history = client.get(f"/api/reviews/{session_id}/messages", params={"user_id": user["id"]})
    assert filtered_history.status_code == 200
    filtered_serialized = json.dumps(filtered_history.json(), ensure_ascii=False)
    assert legacy_feedback not in filtered_serialized


def test_review_warmup_model_judgement_selects_stage_from_free_text(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id)
    created = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert created.status_code == 201

    monkeypatch.setattr(
        review_repository,
        "build_sdk_review_warmup_judgement_response",
        lambda context: {
            "result": "correct",
            "confidence": "high",
            "feedback": "模型判断这段回答已经覆盖核心风险。",
            "generation_source": "llm",
            "generation_model": "fake-stage-judge",
        },
    )
    response = client.post(
        f"/api/reviews/{created.json()['session_id']}/warmup-result",
        json={
            "user_id": user["id"],
            "action": "answer",
            "answer": "我会先核对补丁证据是否真正覆盖风险，再决定是否接受。",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["review_stage"] == "exercise"
    assert body["warmup"]["recall_level"] == "clear"
    assert body["warmup"]["judgement_source"] == "llm"
    assert body["warmup"]["judgement_model"] == "fake-stage-judge"


def test_review_messages_cross_user_returns_session_not_found(client: TestClient) -> None:
    owner, plan = _confirmed_plan(client, language="javascript")
    other = _create_user(client)
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id)
    created = client.post(
        "/api/reviews/start",
        json={"user_id": owner["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert created.status_code == 201

    history = client.get(
        f"/api/reviews/{created.json()['session_id']}/messages",
        params={"user_id": other["id"]},
    )
    assert history.status_code == 404
    assert history.json()["error"]["code"] == "SESSION_NOT_FOUND"

    warmup = client.post(
        f"/api/reviews/{created.json()['session_id']}/warmup-result",
        json={"user_id": other["id"], "action": "skip"},
    )
    assert warmup.status_code == 404
    assert warmup.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_review_warmup_branches_do_not_create_fsrs_evidence(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id, reps=4)

    start = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert start.status_code == 201
    session_id = start.json()["session_id"]

    skipped = client.post(f"/api/reviews/{session_id}/warmup-result", json={"action": "skip"})
    assert skipped.status_code == 200
    skipped_body = skipped.json()
    assert skipped_body["review_stage"] == "exercise"
    assert skipped_body["current_node"]["type"] == "exercise"
    assert skipped_body["warmup"]["result"] == "skipped"
    assert skipped_body["warmup"]["recall_level"] == "skipped"
    assert skipped_body["review_stage_state"]["batch"]["difficulty_bias"] == "lower"
    assert skipped_body["review_stage_state"]["session_diagnosis"]["skip_count"] == 1

    with connect() as conn:
        counts = conn.execute(
            """
            SELECT
              (SELECT count(*) FROM attempts WHERE session_id = %s) AS attempt_count,
              (SELECT count(*) FROM review_logs WHERE knowledge_point_id = %s) AS review_log_count,
              (SELECT reps FROM review_states WHERE knowledge_point_id = %s) AS reps
            """,
            (session_id, knowledge_point_id, knowledge_point_id),
        ).fetchone()
    assert counts is not None
    assert counts["attempt_count"] == 0
    assert counts["review_log_count"] == 0
    assert counts["reps"] == 4

    with connect() as conn:
        conn.execute("UPDATE learning_sessions SET status = 'finished' WHERE id = %s", (session_id,))
        conn.commit()

    again = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert again.status_code == 201
    repair_session_id = again.json()["session_id"]

    first_wrong = client.post(
        f"/api/reviews/{repair_session_id}/warmup-result",
        json={"action": "answer", "answer": "随便试一下"},
    )
    assert first_wrong.status_code == 200
    assert first_wrong.json()["review_stage"] == "warmup_repair"
    assert first_wrong.json()["current_node"]["type"] == "warmup_repair"
    assert first_wrong.json()["warmup"]["repair_count"] == 1
    assert first_wrong.json()["warmup"]["recall_level"] == "wrong"
    first_wrong_feedback = first_wrong.json()["warmup"]["feedback"]
    assert "先做一次短修正" not in first_wrong_feedback
    assert "再修正一下" not in first_wrong_feedback
    assert "正式复习题" not in first_wrong_feedback
    assert first_wrong.json()["warmup"]["question"] in first_wrong_feedback
    assert first_wrong.json()["next_action"] == "retry_same"

    second_wrong = client.post(
        f"/api/reviews/{repair_session_id}/warmup-result",
        json={"action": "answer", "answer": "还是随便猜"},
    )
    assert second_wrong.status_code == 200
    second_body = second_wrong.json()
    assert second_body["review_stage"] == "exercise"
    assert second_body["current_node"]["type"] == "exercise"
    assert second_body["review_stage_state"]["variant"]["guided"] is True
    assert second_body["review_stage_state"]["exercise_plan"][0]["guided"] is True


def test_review_warmup_unclear_judgement_enters_repair_without_fsrs_evidence(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id, reps=3)

    start = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert start.status_code == 201
    session_id = start.json()["session_id"]

    unclear = client.post(
        f"/api/reviews/{session_id}/warmup-result",
        json={"action": "answer", "answer": "不知道"},
    )
    assert unclear.status_code == 200
    body = unclear.json()
    assert body["review_stage"] == "warmup_repair"
    assert body["current_node"]["type"] == "warmup_repair"
    assert body["warmup"]["result"] == "unclear"
    assert body["warmup"]["recall_level"] == "fuzzy"
    assert body["warmup"]["judgement_ready"] is True
    assert body["next_action"] == "retry_same"

    with connect() as conn:
        stored = conn.execute(
            """
            SELECT review_stage, review_stage_state_json
            FROM learning_sessions
            WHERE id = %s
            """,
            (session_id,),
        ).fetchone()
        counts = conn.execute(
            """
            SELECT
              (SELECT count(*) FROM attempts WHERE session_id = %s) AS attempt_count,
              (SELECT count(*) FROM review_logs WHERE knowledge_point_id = %s) AS review_log_count,
              (SELECT reps FROM review_states WHERE knowledge_point_id = %s) AS reps
            """,
            (session_id, knowledge_point_id, knowledge_point_id),
        ).fetchone()
    assert stored is not None
    assert stored["review_stage"] == "warmup_repair"
    assert stored["review_stage_state_json"]["schema_version"] == "review_batch_v1"
    assert stored["review_stage_state_json"]["warmup"]["result"] == "unclear"
    assert stored["review_stage_state_json"]["warmup"]["recall_level"] == "fuzzy"
    assert counts is not None
    assert counts["attempt_count"] == 0
    assert counts["review_log_count"] == 0
    assert counts["reps"] == 3


def test_review_ai_patch_scoring_requires_grounded_evidence(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id, reps=1)
    with connect() as conn:
        conn.execute(
            "UPDATE knowledge_points SET weak_points_json = %s::jsonb WHERE id = %s",
            (json.dumps(["review_patch_evidence"]), knowledge_point_id),
        )
        conn.commit()

    start = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert start.status_code == 201
    review_session = start.json()
    exercise = _enter_formal_review(client, review_session, user_id=str(user["id"]))
    assert exercise["exercise_type"] == "review_ai_patch"
    metadata = exercise["metadata_json"]
    assert metadata["requirement"]
    assert metadata["ai_diff"]
    assert "rubric" in metadata
    assert not exercise["solution_reference"]

    payload = {
        "exercise_id": exercise["id"],
        "submit_version": 1,
        "review_ai_patch_answer": {
            "verdict": "fail",
            "evidence": "tests passed",
            "knowledge_point_risk": "状态作用域风险",
            "next_action": "request_change",
        },
    }
    submitted = client.post(f"/api/reviews/{review_session['session_id']}/exercise-result", json=payload)
    assert submitted.status_code == 200
    submit_body = submitted.json()
    assert submit_body["score_breakdown"]["verdict_correctness"] == 2
    assert submit_body["score_breakdown"]["evidence_grounding"] == 1
    assert submit_body["fsrs_rating"] == "Hard"
    assert submit_body["result"] == "partial"
    assert submit_body["code_completion_result"]["review_ai_patch_result"]["evidence_quality"] == "weak"
    assert submit_body["current_node"]["type"] == "exercise"
    assert submit_body["next_action"] == "next_exercise"
    assert "ReviewState" not in submit_body
    assert "due_at" not in submit_body

    replayed = client.post(f"/api/reviews/{review_session['session_id']}/exercise-result", json=payload)
    assert replayed.status_code == 200
    assert replayed.json()["idempotency_replayed"] is True
    assert replayed.json()["attempt_id"] == submit_body["attempt_id"]
    assert "ReviewState" not in replayed.json()

    with connect() as conn:
        attempt = conn.execute(
            """
            SELECT attempt_type, code_completion_result, fsrs_rating
            FROM attempts
            WHERE id = %s
            """,
            (submit_body["attempt_id"],),
        ).fetchone()
    assert attempt is not None
    assert attempt["attempt_type"] == "review_submit"
    assert attempt["fsrs_rating"] == "Hard"
    assert attempt["code_completion_result"]["score_breakdown"]["actionability"] == 2


def test_review_run_and_submit_updates_schedule_once(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id, reps=2)

    start = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert start.status_code == 201
    review_session = start.json()
    exercise = _enter_formal_review(client, review_session, user_id=str(user["id"]))

    first_body = _submit_review_exercise_success(
        client,
        session_id=str(review_session["session_id"]),
        exercise=exercise,
    )
    assert first_body["next_action"] == "next_exercise"
    assert "ReviewState" not in first_body
    assert "due_at" not in first_body
    first_next = first_body["review_exercise"]
    assert first_next["id"] != exercise["id"]

    first_replay = client.post(
        f"/api/reviews/{review_session['session_id']}/exercise-result",
        json=first_body["_request_payload"],
    )
    assert first_replay.status_code == 200
    first_replay_body = first_replay.json()
    assert first_replay_body["idempotency_replayed"] is True
    assert first_replay_body["attempt_id"] == first_body["attempt_id"]
    assert first_replay_body["review_exercise"]["id"] == first_next["id"]

    with connect() as conn:
        row = conn.execute(
            "SELECT review_stage_state_json FROM learning_sessions WHERE id = %s",
            (review_session["session_id"],),
        ).fetchone()
        assert row is not None
        legacy_state = dict(row["review_stage_state_json"])
        legacy_plan = []
        for entry in legacy_state["exercise_plan"]:
            legacy_entry = dict(entry)
            if legacy_entry.get("attempt_id") == first_body["attempt_id"]:
                legacy_entry.pop("exercise", None)
                legacy_entry.pop("exercise_title", None)
                legacy_entry.pop("submitted_code", None)
                legacy_entry.pop("filled_blanks", None)
                legacy_entry.pop("explanation", None)
                legacy_entry.pop("review_ai_patch_answer", None)
                legacy_entry.pop("feedback", None)
                legacy_entry.pop("weak_points", None)
                legacy_entry.pop("code_completion_result", None)
                legacy_entry.pop("test_pass_rate", None)
                legacy_entry.pop("hint_usage_count", None)
                legacy_entry.pop("error_count", None)
                legacy_entry.pop("error_cause", None)
            legacy_plan.append(legacy_entry)
        legacy_state["exercise_plan"] = legacy_plan
        conn.execute(
            "UPDATE learning_sessions SET review_stage_state_json = %s::jsonb WHERE id = %s",
            (json.dumps(legacy_state), review_session["session_id"]),
        )
        conn.commit()

    resumed = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert resumed.status_code == 200
    resumed_body = resumed.json()
    assert resumed_body["current_node"]["exercise"]["id"] == first_next["id"]
    completed_entries = [
        entry
        for entry in resumed_body["review_stage_state"]["exercise_plan"]
        if entry.get("attempt_id") == first_body["attempt_id"]
    ]
    assert len(completed_entries) == 1
    assert completed_entries[0]["exercise_title"] == exercise["title"]
    assert completed_entries[0]["exercise"]["id"] == exercise["id"]
    assert completed_entries[0]["submitted_code"].strip() == str(exercise["solution_reference"]).strip()
    assert completed_entries[0]["filled_blanks"]["blank_1"]
    assert completed_entries[0]["explanation"] == "状态变量放在回调外层，所以多次点击会共享同一个 count。"
    assert completed_entries[0]["feedback"] == first_body["feedback"]
    assert completed_entries[0]["code_completion_result"]["feedback"] == first_body["feedback"]

    with connect() as conn:
        intermediate_state = conn.execute(
            "SELECT reps, last_attempt_id FROM review_states WHERE knowledge_point_id = %s",
            (knowledge_point_id,),
        ).fetchone()
        intermediate_logs = conn.execute(
            "SELECT count(*) AS count FROM review_logs WHERE knowledge_point_id = %s AND source = 'review_submit'",
            (knowledge_point_id,),
        ).fetchone()
        intermediate_submit_attempts = conn.execute(
            "SELECT count(*) AS count FROM attempts WHERE session_id = %s AND attempt_type = 'review_submit'",
            (review_session["session_id"],),
        ).fetchone()
        intermediate_profile = get_learner_profile(conn, str(user["id"]))
    assert intermediate_state is not None
    assert intermediate_state["reps"] == 2
    assert intermediate_state["last_attempt_id"] is None
    assert intermediate_logs is not None
    assert intermediate_logs["count"] == 0
    assert intermediate_submit_attempts is not None
    assert intermediate_submit_attempts["count"] == 1
    assert intermediate_profile is None

    second_body = _submit_review_exercise_success(
        client,
        session_id=str(review_session["session_id"]),
        exercise=first_next,
    )
    assert second_body["next_action"] == "next_exercise"
    assert "ReviewState" not in second_body
    second_next = second_body["review_exercise"]
    assert second_next["id"] not in {exercise["id"], first_next["id"]}

    final_body = _submit_review_exercise_success(
        client,
        session_id=str(review_session["session_id"]),
        exercise=second_next,
    )
    assert final_body["current_node"]["type"] == "final_summary"
    assert final_body["final_result"]["final_fsrs_rating"] in {"Good", "Easy"}
    assert final_body["ReviewState"]["last_attempt_id"] == final_body["attempt_id"]
    assert final_body["ReviewState"]["review_count"] == 3
    assert final_body["due_at"] == final_body["ReviewState"]["due_at"]
    assert final_body["forget_risk"] in {"low", "normal", "high"}

    replay_payload = final_body["_request_payload"]
    replayed = client.post(f"/api/reviews/{review_session['session_id']}/exercise-result", json=replay_payload)
    assert replayed.status_code == 200
    assert replayed.json()["idempotency_replayed"] is True
    assert replayed.json()["ReviewState"]["review_count"] == 3

    with connect() as conn:
        state = conn.execute(
            "SELECT reps, last_attempt_id FROM review_states WHERE knowledge_point_id = %s",
            (knowledge_point_id,),
        ).fetchone()
        log_count = conn.execute(
            """
            SELECT count(*) AS count
            FROM review_logs
            WHERE attempt_id = %s AND source = 'review_submit'
            """,
            (final_body["attempt_id"],),
        ).fetchone()
        profile = get_learner_profile(conn, str(user["id"]))
    assert state is not None
    assert state["reps"] == 3
    assert str(state["last_attempt_id"]) == final_body["attempt_id"]
    assert log_count is not None
    assert log_count["count"] == 1
    assert profile is not None
    assert profile["pace_indicators"]["last_review_rating"] == final_body["final_result"]["final_fsrs_rating"]
    assert profile["pace_indicators"]["mastery_signal"] == "review_recovered"


def test_review_submit_returns_recoverable_error_when_ready_pool_cannot_advance(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id, reps=2)

    start = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert start.status_code == 201
    review_session = start.json()
    exercise = _enter_formal_review(client, review_session, user_id=str(user["id"]))

    with connect() as conn:
        state = conn.execute(
            "SELECT review_stage_state_json FROM learning_sessions WHERE id = %s",
            (review_session["session_id"],),
        ).fetchone()
        assert state is not None
        seed_bank_id = state["review_stage_state_json"]["pool"]["seed_bank_id"]
        conn.execute(
            "UPDATE review_seed_banks SET seeds_json = '[]'::jsonb, seed_count = 0 WHERE id = %s",
            (seed_bank_id,),
        )
        conn.commit()

    filled_blanks = _filled_blanks_for(exercise)
    run = client.post(
        f"/api/learning-sessions/{review_session['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": exercise["solution_reference"],
            "filled_blanks": filled_blanks,
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    assert run.status_code == 201
    submitted = client.post(
        f"/api/reviews/{review_session['session_id']}/exercise-result",
        json={
            "exercise_id": exercise["id"],
            "attempt_id": run.json()["attempt_id"],
            "code": exercise["solution_reference"],
            "filled_blanks": filled_blanks,
            "submit_version": 1,
            "explanation": "状态变量放在回调外层，所以多次点击会共享同一个 count。",
            "hint_usage_count": 0,
            "error_count": 0,
            "explanation_check": {
                "result": "passed",
                "score": 2,
                "feedback": "能解释状态共享原因。",
            },
        },
    )

    assert submitted.status_code == 409
    error = submitted.json()["error"]
    assert error["code"] == "REVIEW_ADAPTIVE_SUPPLEMENT_FAILED"
    assert error["recoverable"] is True

    with connect() as conn:
        persisted = conn.execute(
            """
            SELECT status, review_stage, review_stage_state_json
            FROM learning_sessions
            WHERE id = %s
            """,
            (review_session["session_id"],),
        ).fetchone()
        counts = conn.execute(
            """
            SELECT
              (SELECT count(*) FROM review_logs WHERE knowledge_point_id = %s) AS review_log_count,
              (SELECT reps FROM review_states WHERE knowledge_point_id = %s) AS reps,
              (SELECT count(*) FROM attempts WHERE session_id = %s AND attempt_type = 'review_submit') AS submit_attempt_count
            """,
            (knowledge_point_id, knowledge_point_id, review_session["session_id"]),
        ).fetchone()
    assert persisted is not None
    assert persisted["status"] == "active"
    assert persisted["review_stage"] == "exercise"
    assert persisted["review_stage_state_json"]["pool"]["adaptive_supplement_status"] == "needed"
    assert counts is not None
    assert counts["review_log_count"] == 0
    assert counts["reps"] == 2
    assert counts["submit_attempt_count"] == 1


def test_review_batch_final_rating_aggregation_rules() -> None:
    easy_rating, easy_result = review_repository._aggregate_review_batch_rating(  # noqa: SLF001
        _batch_state_for_rating(
            [
                _batch_entry("basic_application", result="passed", score=8, is_core=True),
                _batch_entry("concept_explanation", result="passed", score=8, is_core=True),
                _batch_entry("debugging", result="passed", score=8, is_core=True),
            ]
        )
    )
    assert easy_rating == "Easy"
    assert easy_result["result"] == "passed"

    good_rating, good_result = review_repository._aggregate_review_batch_rating(  # noqa: SLF001
        _batch_state_for_rating(
            [
                _batch_entry("basic_application", result="passed", score=8, is_core=True),
                _batch_entry("concept_explanation", result="passed", score=7, is_core=True),
                _batch_entry("transfer_or_review", result="failed", score=3, fsrs_rating="Again", is_core=False),
            ]
        )
    )
    assert good_rating == "Good"
    assert good_result["fail_count"] == 1

    core_rating, _ = review_repository._aggregate_review_batch_rating(  # noqa: SLF001
        _batch_state_for_rating(
            [
                _batch_entry("basic_application", result="passed", score=8, is_core=True),
                _batch_entry("concept_explanation", result="partial", score=5, fsrs_rating="Hard", is_core=True),
                _batch_entry("debugging", result="passed", score=8, is_core=True),
            ]
        )
    )
    assert core_rating != "Easy"
    assert core_rating == "Hard"

    skipped_rating, skipped_result = review_repository._aggregate_review_batch_rating(  # noqa: SLF001
        _batch_state_for_rating(
            [
                _batch_entry("basic_application", result="passed", score=8, is_core=True),
                _batch_entry("concept_explanation", result="passed", score=8, is_core=True),
                _batch_entry("debugging", result="passed", score=8, is_core=True),
            ],
            skip_count=2,
        )
    )
    assert skipped_rating == "Again"
    assert skipped_result["skip_count"] == 2


def test_review_routes_langgraph_flag_on_invokes_start_and_submit_graph(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id, reps=2)
    captured: list[dict[str, object]] = []

    monkeypatch.setattr(reviews_route, "get_settings", lambda: Settings(langgraph_enabled=True))

    def fake_invoke_review_orchestration(**kwargs):  # type: ignore[no-untyped-def]
        captured.append(dict(kwargs))
        action = kwargs["action"]
        return {
            "next_action": (
                "submit_and_update"
                if action == "submit"
                else "warmup"
                if action == "warmup"
                else "start_session"
            ),
            "intent_type": "tool_call" if action == "warmup" else "persistence",
            "intent_payload": {
                "target": "attempt_and_fsrs" if action == "submit" else "review_session",
                "tool": "evaluate_warmup" if action == "warmup" else "",
            },
        }

    monkeypatch.setattr(
        reviews_route,
        "invoke_review_orchestration",
        fake_invoke_review_orchestration,
    )

    start = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert start.status_code == 201
    review_session = start.json()
    exercise = _enter_formal_review(client, review_session, user_id=str(user["id"]))
    filled_blanks = _filled_blanks_for(exercise)

    warmup = client.post(
        f"/api/reviews/{review_session['session_id']}/warmup-result",
        json={"action": "skip"},
    )
    assert warmup.status_code == 200

    run = client.post(
        f"/api/learning-sessions/{review_session['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": exercise["solution_reference"],
            "filled_blanks": filled_blanks,
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    assert run.status_code == 201

    submitted = client.post(
        f"/api/reviews/{review_session['session_id']}/exercise-result",
        json={
            "exercise_id": exercise["id"],
            "attempt_id": run.json()["attempt_id"],
            "code": exercise["solution_reference"],
            "filled_blanks": filled_blanks,
            "submit_version": 1,
            "explanation": "状态变量放在回调外层，所以多次点击会共享同一个 count。",
            "hint_usage_count": 0,
            "error_count": 0,
            "explanation_check": {
                "result": "passed",
                "score": 2,
                "feedback": "能解释状态共享原因。",
            },
        },
    )
    assert submitted.status_code == 200

    start_call = next(call for call in captured if call["action"] == "start")
    warmup_call = next(call for call in captured if call["action"] == "warmup")
    submit_call = next(call for call in captured if call["action"] == "submit")
    assert start_call["is_due"] is True
    assert start_call["has_active_session"] is False
    assert start_call["knowledge_point_id"] == knowledge_point_id
    assert warmup_call["session_id"] == review_session["session_id"]
    assert warmup_call["knowledge_point_id"] == knowledge_point_id
    assert submit_call["session_id"] == review_session["session_id"]
    assert submit_call["explanation_ready"] is True


def test_review_start_invalid_graph_intent_falls_back_to_service_path(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id, reps=2)
    captured: list[dict[str, object]] = []

    monkeypatch.setattr(reviews_route, "get_settings", lambda: Settings(langgraph_enabled=True))

    def fake_invoke_review_orchestration(**kwargs):  # type: ignore[no-untyped-def]
        captured.append(dict(kwargs))
        return {
            "next_action": "reject_not_due",
            "intent_type": "persistence",
            "intent_payload": {
                "target": "delete_review_state",
                "stack_trace": "provider payload sk-secret",
            },
        }

    monkeypatch.setattr(
        reviews_route,
        "invoke_review_orchestration",
        fake_invoke_review_orchestration,
    )

    start = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )

    assert start.status_code == 201
    assert captured
    payload = json.dumps(start.json(), ensure_ascii=False)
    assert "delete_review_state" not in payload
    assert "provider payload" not in payload
    assert "sk-secret" not in payload


def test_review_submit_blocked_explanation_judgement_does_not_write_attempt(
    client: TestClient,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id, reps=2)

    start = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert start.status_code == 201
    review_session = start.json()
    exercise = _enter_formal_review(client, review_session, user_id=str(user["id"]))
    filled_blanks = _filled_blanks_for(exercise)

    run = client.post(
        f"/api/learning-sessions/{review_session['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": exercise["solution_reference"],
            "filled_blanks": filled_blanks,
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    assert run.status_code == 201

    payload = {
        "exercise_id": exercise["id"],
        "attempt_id": run.json()["attempt_id"],
        "code": exercise["solution_reference"],
        "filled_blanks": filled_blanks,
        "submit_version": 1,
        "explanation": "状态变量会共享。",
        "hint_usage_count": 0,
        "error_count": 0,
        "explanation_check": {
            "result": "passed",
            "score": 2,
            "feedback": "反馈不足以确认薄弱点。",
            "judgements": {
                "review_explanation_sufficiency": {
                    "status": "ambiguous",
                    "clarification_question": "请再补充这次提交为什么能覆盖状态作用域风险。",
                },
                "weak_point_signal": {"status": "confirmed"},
                "repair_needed": {"status": "confirmed"},
            },
        },
    }
    submitted = client.post(f"/api/reviews/{review_session['session_id']}/exercise-result", json=payload)

    assert submitted.status_code == 200
    body = submitted.json()
    assert body["judgement_ready"] is False
    assert body["next_action"] == "retry_same"
    assert "attempt_id" not in body

    with connect() as conn:
        counts = conn.execute(
            """
            SELECT
              (SELECT count(*) FROM attempts WHERE session_id = %s) AS attempt_count,
              (SELECT count(*) FROM review_logs WHERE knowledge_point_id = %s) AS review_log_count,
              (SELECT reps FROM review_states WHERE knowledge_point_id = %s) AS reps
            """,
            (review_session["session_id"], knowledge_point_id, knowledge_point_id),
        ).fetchone()
    assert counts is not None
    assert counts["attempt_count"] == 1
    assert counts["review_log_count"] == 0
    assert counts["reps"] == 2


def test_run_attempt_does_not_update_review_state_and_scheduler_is_idempotent(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    start = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": knowledge_point_id,
        },
    )
    session = start.json()
    exercise = _unlock_practice_exercise(client, session)
    filled_blanks = _filled_blanks_for(exercise)

    run = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": exercise["solution_reference"],
            "filled_blanks": filled_blanks,
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    assert run.status_code == 201

    with connect() as conn:
        state_after_run = conn.execute(
            "SELECT reps, last_attempt_id FROM review_states WHERE knowledge_point_id = %s",
            (knowledge_point_id,),
        ).fetchone()
    assert state_after_run is not None
    assert state_after_run["reps"] == 0
    assert state_after_run["last_attempt_id"] is None

    explanation = client.post(
        f"/api/learning-sessions/{session['session_id']}/attempts/{run.json()['attempt_id']}/check-explanation",
        json={
            "explanation": "状态变量放在回调外层，所以多次点击会共享同一个 count；如果写在回调里，每次点击都会重新初始化。",
            "focus": "core_logic",
            "round": 1,
        },
    )
    assert explanation.status_code == 200
    submit = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/submit",
        json={
            "attempt_id": run.json()["attempt_id"],
            "code": exercise["solution_reference"],
            "filled_blanks": filled_blanks,
            "submit_version": 1,
            "explanation": "状态变量放在回调外层，所以多次点击会共享同一个 count；如果写在回调里，每次点击都会重新初始化。",
            "hint_usage_count": 0,
            "error_count": 0,
        },
    )
    assert submit.status_code == 200
    submit_body = submit.json()

    with connect() as conn:
        replayed = apply_attempt_review_update(
            conn,
            knowledge_point_id=knowledge_point_id,
            attempt_id=submit_body["attempt_id"],
            source="learn_submit",
            request_id=None,
        )
        conn.commit()
        state_after_replay = conn.execute(
            "SELECT reps FROM review_states WHERE knowledge_point_id = %s",
            (knowledge_point_id,),
        ).fetchone()
        log_count = conn.execute(
            """
            SELECT count(*) AS count
            FROM review_logs
            WHERE attempt_id = %s AND source = 'learn_submit'
            """,
            (submit_body["attempt_id"],),
        ).fetchone()
    assert replayed["ReviewState"]["review_count"] == 1
    assert state_after_replay is not None
    assert state_after_replay["reps"] == 1
    assert log_count is not None
    assert log_count["count"] == 1


def _confirmed_plan(client: TestClient, *, language: str) -> tuple[dict[str, object], dict[str, object]]:
    user = _create_user(client)
    course = _course_by_language(client, language)
    draft_response = client.post(
        "/api/plans/generate",
        json={
            "user_id": user["id"],
            "mode": "goal_based",
            "goal_text": f"Practice {language} review scheduling validation.",
            "course_id": course["id"],
        },
    )
    assert draft_response.status_code == 200
    draft = draft_response.json()["plan_draft"]

    confirm_response = client.post("/api/plans", json={"user_id": user["id"], "plan_draft": draft})
    assert confirm_response.status_code == 201
    return user, confirm_response.json()


def _create_user(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/users",
        json={
            "display_name": f"M4 User {uuid.uuid4().hex[:8]}",
            "learning_style": "practice_first",
            "teaching_preference": "step_by_step",
        },
    )
    assert response.status_code == 201
    user = response.json()["user"]
    assert isinstance(user, dict)
    return user


def _course_by_language(client: TestClient, language: str) -> dict[str, object]:
    response = client.get(f"/api/language-courses?language={language}")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    course = items[0]
    assert isinstance(course, dict)
    return course


def _unlock_practice_exercise(client: TestClient, session: dict[str, object]) -> dict[str, object]:
    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "开始练习，给我题。",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["session_state"]["learning_stage"] == "practice_support"
    tool_calls = body["tool_calls"]
    exercise_tool_call = next(
        (tool_call for tool_call in tool_calls if tool_call["name"] == "show_code_exercise"),
        None,
    )
    assert exercise_tool_call is not None
    exercise = exercise_tool_call["args"]["exercise"]
    assert isinstance(exercise, dict)
    return exercise


def _mark_due(knowledge_point_id: str, *, reps: int = 1) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE review_states
            SET card_state = 'review',
                due_at = now() - interval '5 minutes',
                last_fsrs_rating = 'Good',
                reps = %s
            WHERE knowledge_point_id = %s
            """,
            (reps, knowledge_point_id),
        )
        conn.execute(
            "UPDATE knowledge_points SET status = 'reviewing' WHERE id = %s",
            (knowledge_point_id,),
        )
        conn.commit()


def _filled_blanks_for(exercise: dict[str, object]) -> dict[str, str]:
    blanks = exercise["code_blanks"]
    assert isinstance(blanks, list)
    result: dict[str, str] = {}
    for blank in blanks:
        assert isinstance(blank, dict)
        result[str(blank["blank_key"])] = str(blank["placeholder"])
    return result


def _enter_formal_review(client: TestClient, review_session: Mapping[str, object], *, user_id: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "action": "answer",
        "answer": "状态作用域和测试证据都需要一起检查。",
    }
    if user_id is not None:
        payload["user_id"] = user_id
    warmup = client.post(
        f"/api/reviews/{review_session['session_id']}/warmup-result",
        json=payload,
    )
    assert warmup.status_code == 200
    body = warmup.json()
    if body["current_node"]["type"] == "warmup_repair":
        repair = client.post(
            f"/api/reviews/{review_session['session_id']}/warmup-result",
            json=payload,
        )
        assert repair.status_code == 200
        body = repair.json()
    assert body["current_node"]["type"] == "exercise"
    exercise = body["current_node"]["exercise"]
    assert isinstance(exercise, dict)
    return exercise


def _submit_review_exercise_success(
    client: TestClient,
    *,
    session_id: str,
    exercise: Mapping[str, object],
    submit_version: int = 1,
) -> dict[str, object]:
    if exercise["exercise_type"] == "review_ai_patch":
        payload = {
            "exercise_id": exercise["id"],
            "submit_version": submit_version,
            "review_ai_patch_answer": {
                "verdict": "fail",
                "evidence": "diff shows count moved into the event callback, so repeated clicks reset state",
                "knowledge_point_risk": "count 被移进回调后每次点击都会重新初始化，连续点击不会累加",
                "next_action": "request_change",
            },
        }
    else:
        exercise_dict = dict(exercise)
        filled_blanks = _filled_blanks_for(exercise_dict)
        run = client.post(
            f"/api/learning-sessions/{session_id}/exercises/{exercise['id']}/run",
            json={
                "code": exercise["solution_reference"],
                "filled_blanks": filled_blanks,
                "runtime_profile_id": exercise["runtime_profile"]["id"],
                "run_mode": "visible_tests",
            },
        )
        assert run.status_code == 201
        payload = {
            "exercise_id": exercise["id"],
            "attempt_id": run.json()["attempt_id"],
            "code": exercise["solution_reference"],
            "filled_blanks": filled_blanks,
            "submit_version": submit_version,
            "explanation": "状态变量放在回调外层，所以多次点击会共享同一个 count。",
            "hint_usage_count": 0,
            "error_count": 0,
            "explanation_check": {
                "result": "passed",
                "score": 2,
                "feedback": "能解释状态共享原因。",
            },
        }
    response = client.post(f"/api/reviews/{session_id}/exercise-result", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["attempt_id"]
    assert body["current_node"]["type"] in {"exercise", "final_summary"}
    body["_request_payload"] = payload
    return body


def _batch_entry(
    capability: str,
    *,
    result: str,
    score: int,
    fsrs_rating: str | None = None,
    is_core: bool,
) -> dict[str, object]:
    return {
        "position": 1,
        "candidate_id": f"candidate_{capability}_{result}",
        "exercise_id": f"exercise_{capability}_{result}",
        "status": "completed",
        "attempt_id": f"attempt_{capability}_{result}",
        "capability": capability,
        "exercise_type": "code_blank",
        "focus_tags": [capability],
        "is_core": is_core,
        "result": result,
        "score": score,
        "fsrs_rating": fsrs_rating or ("Good" if result == "passed" else "Hard"),
        "score_breakdown": {"test": score},
        "evidence_quality": "strong",
    }


def _batch_state_for_rating(entries: list[dict[str, object]], *, skip_count: int = 0) -> dict[str, object]:
    covered = sorted({str(entry["capability"]) for entry in entries})
    return {
        "batch": {
            "completed_count": len(entries),
            "coverage": {
                "required_capabilities": ["basic_application", "concept_explanation", "debugging"],
                "covered_capabilities": covered,
                "failed_core_capabilities": [],
                "unresolved_focus_tags": [],
            },
        },
        "session_diagnosis": {
            "skip_count": skip_count,
            "weak_points": [],
            "failed_focus_tags": [],
            "passed_focus_tags": [],
        },
        "exercise_plan": entries,
    }
