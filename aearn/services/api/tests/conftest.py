from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest


from app.agents.harness.contracts import TutorPolicySnapshot, TutorRunSnapshot
from app.agents.harness.skill_catalog import SkillCatalogSnapshot, compile_published_skill_catalog
from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.services.exercises import adaptive_exercise_service
from app.services.exercises.adaptive_exercise_service import GeneratedAdaptiveCandidate
from app.services.repositories import review_seed_bank
from app.services.repositories.review_seed_bank import GeneratedReviewSeedBank
from app.services.tutor.persistence import PostgresTutorRepository

pytest_plugins = ("tutor_public_api_support",)


@pytest.fixture(autouse=True)
def disable_live_adaptive_model_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adaptive_exercise_service, "build_model_candidate", _fake_adaptive_model_candidate)
    monkeypatch.setattr(review_seed_bank, "build_model_review_seed_bank", _fake_review_seed_bank_candidate)


def _fake_adaptive_model_candidate(
    model_context: Mapping[str, object],
    template: object,
) -> GeneratedAdaptiveCandidate:
    fallback = getattr(template, "fallback_payload")
    assert isinstance(fallback, Mapping)
    required_skill_tags = model_context.get("required_skill_tags")
    target_skill_tags = list(required_skill_tags) if isinstance(required_skill_tags, list) else []
    return GeneratedAdaptiveCandidate(
        content={
            "candidate": {
                "title": f"{fallback['title']}：模型生成练习",
                "prompt_markdown": fallback["prompt_markdown"],
                "starter_code": fallback["starter_code"],
                "solution_reference": fallback["solution_reference"],
                "metadata_json": fallback["metadata_json"],
                "exercise_intent": "Align the exercise with the current route knowledge point.",
                "target_skill_tags": target_skill_tags,
                "alignment_claims": target_skill_tags,
            }
        },
        model="fake-adaptive-exercise-model",
    )


def _fake_review_seed_bank_candidate(model_context: Mapping[str, object]) -> GeneratedReviewSeedBank:
    supported_types = model_context.get("supported_exercise_types")
    if not isinstance(supported_types, list) or not supported_types:
        supported = ["explain_code"]
    else:
        supported = [str(item) for item in supported_types]
    target_count = int(model_context.get("target_seed_count") or 10)
    seeds = [
        _fake_review_seed(model_context, exercise_type=supported[index % len(supported)], index=index)
        for index in range(target_count)
    ]
    return GeneratedReviewSeedBank(
        content={"candidate_pool": {"candidates": seeds, "quality_notes": ["fake model-generated review candidate pool"]}},
        model="fake-review-seed-model",
    )


def _fake_review_seed(
    model_context: Mapping[str, object],
    *,
    exercise_type: str,
    index: int,
) -> dict[str, object]:
    knowledge_point_id = str(model_context["knowledge_point_id"])
    title = str(model_context.get("knowledge_point_title") or "当前知识点")
    runtime_profile = model_context.get("runtime_profile")
    runtime_tier = str(runtime_profile.get("runtime_tier") or "") if isinstance(runtime_profile, Mapping) else ""
    language = str(runtime_profile.get("language") or "javascript") if isinstance(runtime_profile, Mapping) else "javascript"
    misconception = _fake_review_misconception(model_context, index)
    base = {
        "id": f"model_seed_{exercise_type}_{index + 1:02d}",
        "exercise_type": exercise_type,
        "difficulty": 2 + (index % 3),
        "capability": _fake_candidate_capability(exercise_type, index=index),
        "target_misconception": misconception,
        "focus_tags": [misconception, "state_scope", "evidence"] if language != "python" else [misconception, "return_value", "stdout"],
        "recommended_for": {
            "recall_levels": ["fuzzy", "wrong", "skipped"],
            "weak_points": [misconception],
            "after_result": ["failed", "partial"],
        },
        "avoid_if": {
            "already_passed_focus_tags": [misconception],
            "recent_candidate_ids": [],
            "unsupported_runtime_tiers": [],
        },
        "knowledge_point_id": knowledge_point_id,
        "runtime_tier": runtime_tier,
        "title": f"{title}：模型生成复习变体 {index + 1}",
        "warmup_question": f"先回忆 {title} 中和 {misconception} 相关的风险点。",
        "warmup_expected_focus": _fake_review_focus(language),
        "warmup_keywords": ["state", "scope", "return", "证据", "风险"],
        "review_focus": _fake_review_focus(language),
        "estimated_minutes": 8,
    }
    if exercise_type == "review_ai_patch":
        return base | _fake_review_patch_seed(language=language, title=title, index=index)
    return base | _fake_practice_review_seed(
        language=language,
        title=title,
        exercise_type=exercise_type,
        index=index,
    )


def _fake_practice_review_seed(*, language: str, title: str, exercise_type: str, index: int) -> dict[str, object]:
    if language == "python":
        starter_code = (
            f"# model generated review variant {index + 1}\n"
            "def summarize_scores(scores):\n"
            "    total = sum(scores)\n"
            "    print(f\"total={total}\")\n"
            "    return __BLANK_1__\n"
        )
        placeholder = "total"
        metadata = {"required_patterns": ["return total"], "stdout_success": "total=9"}
        test_cases = [_fake_visible_case({"scores": [2, 3, 4]}, {"return": 9})]
    else:
        starter_code = (
            f"// model generated review variant {index + 1}\n"
            "const button = document.querySelector(\"#counter-button\");\n"
            "const output = document.querySelector(\"#counter-output\");\n"
            "let count = 0;\n"
            "button.addEventListener(\"click\", () => {\n"
            "  __BLANK_1__;\n"
            "  output.textContent = String(count);\n"
            "});\n"
        )
        placeholder = "count += 1"
        metadata = {
            "required_patterns": ["addEventListener", "count += 1", "output.textContent"],
            "preview_html": {
                "success": "<button id=\"counter-button\">Clicked</button><p id=\"counter-output\">1</p>",
                "failure": "<button id=\"counter-button\">Clicked</button><p id=\"counter-output\">0</p>",
            },
        }
        test_cases = [
            _fake_visible_case({"event": "click"}, {"textContent": "1"}),
            _fake_preview_case({"selector": "#counter-output"}, {"textContent": "1"}, order_index=1),
        ]
    return {
        "prompt_markdown": f"模型生成复习题：围绕 **{title}** 完成变体 {index + 1}，并解释关键风险。",
        "starter_code": starter_code,
        "visible_test_policy": "visible_and_hidden_summary",
        "requires_explanation": True,
        "metadata": _candidate_metadata(
            metadata,
            selection_reason=f"Use {exercise_type} to check {title} misconception {index + 1}.",
            is_core=index % 2 == 0,
        ),
        "code_blanks": [
            {
                "blank_key": "blank_1",
                "placeholder": placeholder,
                "expected_concept": _fake_review_focus(language),
                "acceptable_patterns_json": [{"type": "literal", "value": placeholder}],
                "is_core": True,
                "order_index": 0,
            }
        ],
        "test_cases": test_cases,
    }


def _fake_review_patch_seed(*, language: str, title: str, index: int) -> dict[str, object]:
    original_code = (
        "def summarize_scores(scores):\n    total = sum(scores)\n    print(f\"total={total}\")\n    return total\n"
        if language == "python"
        else (
            "const button = document.querySelector(\"#counter-button\");\n"
            "const output = document.querySelector(\"#counter-output\");\n"
            "let count = 0;\n"
            "button.addEventListener(\"click\", () => {\n"
            "  count += 1;\n"
            "  output.textContent = String(count);\n"
            "});\n"
        )
    )
    ai_diff = (
        "-    return total\n+    print(total)\n+    return None"
        if language == "python"
        else "-let count = 0;\n button.addEventListener(\"click\", () => {\n+  let count = 0;\n   count += 1;"
    )
    expected_risk = (
        "函数不再返回调用方需要的值"
        if language == "python"
        else "count 被移进回调后每次点击都会重新初始化，连续点击不会累加"
    )
    return {
        "prompt_markdown": f"模型生成复习题：审核 AI 对 **{title}** 的第 {index + 1} 个改动。",
        "starter_code": original_code,
        "visible_test_policy": "visible_only",
        "requires_explanation": True,
        "metadata": _candidate_metadata(
            {
                "requirement": "保留原有可见行为，并确保关键状态或返回值仍能被后续调用验证。",
                "original_code": original_code,
                "ai_diff": ai_diff,
                "review_focus": _fake_review_focus(language),
                "expected_risk": expected_risk,
                "expected_verdict": "fail",
                "expected_next_action": "request_change",
            },
            selection_reason=f"Review an AI patch to verify evidence quality for {title}.",
            is_core=True,
        ),
        "rubric": {
            "verdict_correctness": "0-2",
            "evidence_grounding": "0-2",
            "knowledge_point_alignment": "0-2",
            "actionability": "0-2",
        },
        "code_blanks": [],
        "test_cases": [],
    }


def _fake_review_misconception(model_context: Mapping[str, object], index: int) -> str:
    learner_state = model_context.get("learner_state")
    weak_points = learner_state.get("weak_points") if isinstance(learner_state, Mapping) else []
    if isinstance(weak_points, list) and weak_points:
        return str(weak_points[index % len(weak_points)])
    return ("state_scope_error", "return_vs_output", "test_evidence_gap")[index % 3]


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


def _candidate_metadata(
    metadata: Mapping[str, object],
    *,
    selection_reason: str,
    is_core: bool,
) -> dict[str, object]:
    return {
        **dict(metadata),
        "selection_reason": selection_reason,
        "is_core": is_core,
    }


def _fake_review_focus(language: str) -> str:
    if language == "python":
        return "区分 return value 与 stdout，确认调用方能继续使用结果"
    return "状态应位于能跨事件复用的作用域，并用需求、diff 与可见行为共同判断"


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
        "is_critical": True,
        "timeout_ms": 5000,
        "order_index": order_index,
    }

# Child 02 target-only Tutor persistence fixtures. These use real PostgreSQL
# when available and roll all test-owned rows back at fixture teardown.

@dataclass(frozen=True)
class TutorPersistenceFixture:
    connection: psycopg.Connection[dict[str, object]]
    repository: PostgresTutorRepository
    user_id: str
    conversation_id: str
    run: TutorRunSnapshot
    catalog: SkillCatalogSnapshot


def _tutor_database_available() -> bool:
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=2) as conn:
            conn.execute("select 1")
        return True
    except psycopg.OperationalError:
        return False


@pytest.fixture
def tutor_persistence() -> TutorPersistenceFixture:
    if not _tutor_database_available():
        pytest.skip("PostgreSQL is not available; run aearn infra compose for Tutor persistence tests.")
    bootstrap_database()
    with connect() as conn:
        suffix = uuid4().hex[:12]
        user = conn.execute(
            "INSERT INTO users (display_name) VALUES (%s) RETURNING id",
            (f"Tutor Persistence {suffix}",),
        ).fetchone()
        assert user is not None
        user_id = str(user["id"])
        catalog = compile_published_skill_catalog()
        repository = PostgresTutorRepository(conn)
        repository.record_catalog_snapshot(catalog)
        conversation_id = repository.create_conversation(user_id=user_id)
        run = repository.create_run(
            user_id=user_id,
            conversation_id=conversation_id,
            catalog_digest=catalog.digest,
            policy=TutorPolicySnapshot(
                deadline=datetime(2030, 1, 1, tzinfo=UTC),
                max_iterations=3,
                max_model_calls=3,
                max_capability_calls=2,
                max_effects=2,
                context_token_budget=64,
            ),
            origin="interactive",
        )
        try:
            yield TutorPersistenceFixture(
                connection=conn,
                repository=repository,
                user_id=user_id,
                conversation_id=conversation_id,
                run=run,
                catalog=catalog,
            )
        finally:
            conn.rollback()
