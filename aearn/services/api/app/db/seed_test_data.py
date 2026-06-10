from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aearn_worker.review_seed_bank_core import persist_ready_seed_bank

from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.models.onboarding import PlanDraft
from app.services.curriculum.catalog import get_course
from app.services.repositories.learning_session_repository import start_learning_session
from app.services.repositories.local_user_data_repository import reset_user_data
from app.services.repositories.note_repository import create_note
from app.services.repositories.plan_repository import confirm_plan, default_confirm_key, get_plan_detail, request_hash
from app.services.repositories.review_seed_bank import validate_review_seed_bank
from app.services.repositories.user_repository import serialize_user


DEMO_USER_ID = "11111111-1111-4111-8111-111111111111"
DEMO_DISPLAY_NAME = "Aearn Dev Test User"
BOOTSTRAP_SCHEMA_VERSION = "aearn_dev_bootstrap_v1"


def resolve_bootstrap_file_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    first_part = path.parts[0].lower() if path.parts else ""
    aearn_dir = Path(__file__).resolve().parents[4]
    repo_root = aearn_dir.parent
    if first_part == "aearn":
        return repo_root / path
    if first_part == "apps":
        return aearn_dir / path
    return Path.cwd() / path


def seed_test_data(*, bootstrap_file: Path | None = None) -> dict[str, object]:
    bootstrap_database()
    with connect() as conn:
        user = _ensure_demo_user(conn)
        reset_user_data(conn, str(user["id"]))
        course = get_course(conn, language="javascript")
        if course is None:
            raise RuntimeError("javascript beginner course is missing; run database bootstrap first")

        draft = _demo_plan_draft(user_id=str(user["id"]), course_id=str(course["id"]))
        body = {"user_id": str(user["id"]), "plan_draft": draft.model_dump(mode="json")}
        plan_response, _ = confirm_plan(
            conn,
            user_id=str(user["id"]),
            plan_draft=draft,
            idempotency_key=default_confirm_key(str(user["id"]), draft.draft_id),
            request_hash=request_hash(body),
        )
        plan_id = str(plan_response["LearningPlan"]["id"])
        knowledge_points = _load_plan_knowledge_points(conn, plan_id=plan_id)
        _shape_demo_learning_state(conn, user_id=str(user["id"]), plan_id=plan_id, knowledge_points=knowledge_points)
        knowledge_points = _load_plan_knowledge_points(conn, plan_id=plan_id)
        _seed_notes(conn, user_id=str(user["id"]), knowledge_points=knowledge_points)
        _seed_ready_review_pools(conn, user_id=str(user["id"]), plan_id=plan_id, knowledge_points=knowledge_points, runtime_profile=course["runtime_profile"])

        plan_detail = get_plan_detail(conn, plan_id, user_id=str(user["id"]))
        conn.commit()

    result = {
        "schemaVersion": BOOTSTRAP_SCHEMA_VERSION,
        "enabled": True,
        "label": "Aearn local test data",
        "generatedAt": datetime.now(UTC).isoformat(),
        "userId": str(user["id"]),
        "planId": plan_id,
        "defaultRoute": "review",
        "summary": {
            "displayName": user["display_name"],
            "planGoal": plan_response["LearningPlan"]["goal_text"],
            "knowledgePointCount": len(knowledge_points),
            "dueReviewCount": 2,
            "notesCount": 2,
        },
        "plan": plan_detail,
    }
    if bootstrap_file is not None:
        bootstrap_file.parent.mkdir(parents=True, exist_ok=True)
        bootstrap_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _ensure_demo_user(conn: Any) -> dict[str, object]:
    row = conn.execute(
        """
        INSERT INTO users (
          id, display_name, learning_style, teaching_preference, encouragement_preference,
          profession, background_context, preferred_time_slots, reminder_preference, deleted_at
        )
        VALUES (%s, %s, 'practice_first', 'step_by_step', 'direct', %s, %s, %s::jsonb, %s::jsonb, NULL)
        ON CONFLICT (id) DO UPDATE SET
          display_name = EXCLUDED.display_name,
          learning_style = EXCLUDED.learning_style,
          teaching_preference = EXCLUDED.teaching_preference,
          encouragement_preference = EXCLUDED.encouragement_preference,
          profession = EXCLUDED.profession,
          background_context = EXCLUDED.background_context,
          preferred_time_slots = EXCLUDED.preferred_time_slots,
          reminder_preference = EXCLUDED.reminder_preference,
          deleted_at = NULL
        RETURNING *
        """,
        (
            DEMO_USER_ID,
            DEMO_DISPLAY_NAME,
            "AI programming learner",
            "Local deterministic test profile for Aearn desktop QA.",
            json.dumps([{"label": "evening", "start": "20:00", "duration_minutes": 45}]),
            json.dumps({"channel": "local_only", "enabled": False}),
        ),
    )
    user = row.fetchone()
    if user is None:
        raise RuntimeError("demo user upsert returned no row")
    return serialize_user(user)


def _demo_plan_draft(*, user_id: str, course_id: str) -> PlanDraft:
    return PlanDraft.model_validate(
        {
            "draft_id": "dev-test-javascript-route-v1",
            "user_id": user_id,
            "language_course_id": course_id,
            "goal_text": "Use JavaScript to review AI-generated UI behavior and runtime evidence.",
            "language": "javascript",
            "target_level": "beginner",
            "mode": "goal_based",
            "deadline": None,
            "runtime_boundary": {
                "runtime_tier": "browser_preview",
                "unsupported_languages": [],
                "notice": "Local test data uses the browser preview runner for DOM/state exercises.",
            },
            "source_attribution": [
                "MDN Web Docs: EventTarget.addEventListener()",
                "MDN JavaScript Guide: Closures",
                "Aearn local deterministic dev fixture",
            ],
            "modules": [
                {
                    "temp_id": "dev-module-dom-state",
                    "title": "DOM State And Evidence",
                    "description": "Use event handlers, persistent state, and visible output to judge generated code.",
                    "order_index": 0,
                    "is_skippable": False,
                    "is_adjustable": True,
                    "estimated_sessions": 3,
                    "source": "agent_generated",
                    "knowledge_points": [
                        {
                            "temp_id": "dev-kp-dom-counter",
                            "title": "DOM Event State Counter",
                            "description": "Keep counter state in a reusable scope and verify UI output after events.",
                            "skill_tags": ["dom_events", "state_scope", "visible_output"],
                            "source": "agent_generated",
                        },
                        {
                            "temp_id": "dev-kp-ai-patch-evidence",
                            "title": "AI Patch Review Evidence",
                            "description": "Judge AI code patches with requirement, diff, runtime behavior, and evidence.",
                            "skill_tags": ["ai_patch_review", "evidence", "risk_detection"],
                            "source": "agent_generated",
                        },
                        {
                            "temp_id": "dev-kp-closure-persistence",
                            "title": "Closure State Persistence",
                            "description": "Explain why closure state survives repeated event callbacks.",
                            "skill_tags": ["closures", "state_scope", "debugging"],
                            "source": "agent_generated",
                        },
                    ],
                },
                {
                    "temp_id": "dev-module-runtime-guardrails",
                    "title": "Runtime Guardrails",
                    "description": "Connect visible results, test evidence, and debug output before accepting generated code.",
                    "order_index": 1,
                    "is_skippable": True,
                    "is_adjustable": True,
                    "estimated_sessions": 2,
                    "source": "agent_generated",
                    "knowledge_points": [
                        {
                            "temp_id": "dev-kp-async-guardrails",
                            "title": "Async Result Guardrails",
                            "description": "Separate event timing from final observable results when reviewing generated UI code.",
                            "skill_tags": ["async", "runtime_evidence", "guardrails"],
                            "source": "agent_generated",
                        },
                        {
                            "temp_id": "dev-kp-readable-debug-output",
                            "title": "Readable Debug Output",
                            "description": "Use debug output to explain behavior without replacing runtime assertions.",
                            "skill_tags": ["debug_output", "assertions", "explanation"],
                            "source": "agent_generated",
                        },
                    ],
                },
            ],
        }
    )


def _load_plan_knowledge_points(conn: Any, *, plan_id: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT
          knowledge_points.*,
          plan_modules.plan_id,
          plan_modules.title AS module_title,
          language_courses.runtime_profile_id,
          runtime_profiles.slug AS runtime_profile_slug,
          runtime_profiles.runtime_tier,
          runtime_profiles.language AS runtime_language,
          runtime_profiles.runner,
          runtime_profiles.supports_realtime_preview,
          runtime_profiles.supports_stdout,
          runtime_profiles.supports_tests,
          runtime_profiles.compile_required,
          runtime_profiles.timeout_ms,
          runtime_profiles.memory_limit_mb,
          runtime_profiles.sandbox_policy,
          review_states.card_state,
          review_states.due_at,
          review_states.reps,
          review_states.lapses,
          review_states.last_fsrs_rating
        FROM knowledge_points
        JOIN plan_modules ON plan_modules.id = knowledge_points.module_id
        JOIN language_courses ON language_courses.id = knowledge_points.language_course_id
        JOIN runtime_profiles ON runtime_profiles.id = language_courses.runtime_profile_id
        JOIN review_states ON review_states.knowledge_point_id = knowledge_points.id
        WHERE plan_modules.plan_id = %s
          AND knowledge_points.deleted_at IS NULL
        ORDER BY plan_modules.order_index, knowledge_points.order_index
        """,
        (plan_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _shape_demo_learning_state(
    conn: Any,
    *,
    user_id: str,
    plan_id: str,
    knowledge_points: Sequence[Mapping[str, object]],
) -> None:
    if len(knowledge_points) < 5:
        raise RuntimeError("demo plan must have at least five knowledge points")
    now = datetime.now(UTC)
    states = [
        {
            "status": "learning",
            "mastery": 0.28,
            "weak_points": ["event_state_scope"],
            "card_state": "learning",
            "due_at": None,
            "last_rating": None,
            "reps": 0,
            "lapses": 0,
        },
        {
            "status": "reviewing",
            "mastery": 0.42,
            "weak_points": ["state_scope_error", "test_evidence_gap"],
            "card_state": "relearning",
            "due_at": now - timedelta(hours=4),
            "last_rating": "Again",
            "reps": 2,
            "lapses": 1,
        },
        {
            "status": "reviewing",
            "mastery": 0.58,
            "weak_points": ["closure_lifetime"],
            "card_state": "review",
            "due_at": now - timedelta(minutes=45),
            "last_rating": "Hard",
            "reps": 3,
            "lapses": 0,
        },
        {
            "status": "pending",
            "mastery": 0.0,
            "weak_points": [],
            "card_state": "new",
            "due_at": None,
            "last_rating": None,
            "reps": 0,
            "lapses": 0,
        },
        {
            "status": "mastered",
            "mastery": 0.92,
            "weak_points": [],
            "card_state": "review",
            "due_at": now + timedelta(days=3),
            "last_rating": "Easy",
            "reps": 5,
            "lapses": 0,
        },
    ]
    for index, (point, state) in enumerate(zip(knowledge_points, states, strict=True)):
        conn.execute(
            """
            UPDATE knowledge_points
            SET status = %s,
                mastery_score = %s,
                weak_points_json = %s::jsonb,
                last_exercise_result = %s,
                last_exercise_score = %s,
                last_exercise_breakdown_json = %s::jsonb
            WHERE id = %s
            """,
            (
                state["status"],
                state["mastery"],
                json.dumps(state["weak_points"], ensure_ascii=False),
                "passed" if index == 4 else "partial" if index in {1, 2} else None,
                7 if index == 4 else 4 if index in {1, 2} else None,
                json.dumps({"dev_seed": True, "focus": state["weak_points"]}, ensure_ascii=False),
                str(point["id"]),
            ),
        )
        conn.execute(
            """
            UPDATE review_states
            SET card_state = %s,
                stability = %s,
                difficulty = %s,
                due_at = %s,
                reps = %s,
                lapses = %s,
                last_review_at = %s,
                last_fsrs_rating = %s,
                scheduler_version = 'dev_seed_fixture',
                fsrs_parameters = %s::jsonb,
                suspended_at = NULL
            WHERE user_id = %s
              AND plan_id = %s
              AND knowledge_point_id = %s
            """,
            (
                state["card_state"],
                0.3 if state["last_rating"] == "Again" else 2.4 if state["last_rating"] == "Hard" else 8.0 if state["last_rating"] == "Easy" else None,
                8.4 if state["last_rating"] == "Again" else 6.2 if state["last_rating"] == "Hard" else 3.2 if state["last_rating"] == "Easy" else None,
                state["due_at"],
                state["reps"],
                state["lapses"],
                now - timedelta(days=1) if state["last_rating"] else None,
                state["last_rating"],
                json.dumps({"dev_seed": True}, ensure_ascii=False),
                user_id,
                plan_id,
                str(point["id"]),
            ),
        )

    learning_response, _ = start_learning_session(
        conn,
        user_id=user_id,
        plan_id=plan_id,
        knowledge_point_id=str(knowledge_points[0]["id"]),
        request_id="dev-seed-learning-session",
    )
    session_id = str(learning_response["session_id"])
    conn.execute(
        """
        UPDATE learning_sessions
        SET started_at = %s,
            summary_text = %s,
            learning_stage = 'documentation_reading',
            learning_stage_state_json = learning_stage_state_json || %s::jsonb
        WHERE id = %s
        """,
        (
            now - timedelta(days=4),
            "上次停在 DOM Event State Counter 的文档阅读阶段，可继续学习或转入复习。",
            json.dumps({"dev_seed": True}, ensure_ascii=False),
            session_id,
        ),
    )
    conn.execute(
        """
        UPDATE learning_plans
        SET current_module_id = %s,
            overall_progress = 0.36
        WHERE id = %s
        """,
        (str(knowledge_points[0]["module_id"]), plan_id),
    )


def _seed_notes(conn: Any, *, user_id: str, knowledge_points: Sequence[Mapping[str, object]]) -> None:
    note_specs = [
        (
            knowledge_points[0],
            "DOM state checkpoint",
            "事件回调之间要复用的状态不要放进回调内部；运行结果需要看可见输出和断言。",
        ),
        (
            knowledge_points[1],
            "AI patch review checklist",
            "先比对 requirement，再看 diff 是否改变状态生命周期，最后用 runtime evidence 支撑 verdict。",
        ),
    ]
    for point, title, content in note_specs:
        note, _ = create_note(
            conn,
            user_id=user_id,
            knowledge_point_id=str(point["id"]),
            title=title,
            content_markdown=content,
        )
        conn.execute(
            """
            UPDATE notes
            SET agent_draft_content = %s
            WHERE id = %s
            """,
            (
                f"Agent draft: expand `{title}` into a before/after debugging checklist.",
                note["id"],
            ),
        )


def _seed_ready_review_pools(
    conn: Any,
    *,
    user_id: str,
    plan_id: str,
    knowledge_points: Sequence[Mapping[str, object]],
    runtime_profile: Mapping[str, object],
) -> None:
    for point in knowledge_points[1:3]:
        context = dict(point) | {
            "id": str(point["id"]),
            "user_id": user_id,
            "plan_id": plan_id,
            "weak_points_json": point.get("weak_points_json") or ["state_scope_error", "test_evidence_gap"],
            "mastery_score": point.get("mastery_score"),
        }
        seeds = _demo_review_seeds(context, runtime_profile=runtime_profile)
        quality_report = validate_review_seed_bank(seeds, context=context, runtime_profile=runtime_profile)
        quality_report = {
            **quality_report,
            "generation_source": "dev_seed_fixture",
            "generation_model": "none",
            "prompt_version": "dev_seed_v1",
        }
        persist_ready_seed_bank(
            conn,
            user_id=user_id,
            plan_id=plan_id,
            knowledge_point_id=str(point["id"]),
            seeds=seeds,
            quality_report=quality_report,
        )


def _demo_review_seeds(
    context: Mapping[str, object],
    *,
    runtime_profile: Mapping[str, object],
) -> list[dict[str, object]]:
    exercise_types = [
        "code_blank",
        "fix_bug",
        "explain_code",
        "implement_function",
        "review_ai_patch",
        "code_blank",
        "fix_bug",
        "explain_code",
        "implement_function",
        "review_ai_patch",
        "code_blank",
        "implement_function",
    ]
    return [
        _demo_review_seed(context, runtime_profile=runtime_profile, exercise_type=exercise_type, index=index)
        for index, exercise_type in enumerate(exercise_types)
    ]


def _demo_review_seed(
    context: Mapping[str, object],
    *,
    runtime_profile: Mapping[str, object],
    exercise_type: str,
    index: int,
) -> dict[str, object]:
    title = str(context.get("title") or "当前知识点")
    misconception = ("state_scope_error", "event_order_gap", "evidence_gap", "closure_lifetime")[index % 4]
    seed_id = f"dev_seed_{exercise_type}_{index + 1:02d}"
    base = {
        "id": seed_id,
        "exercise_type": exercise_type,
        "difficulty": 2 + (index % 3),
        "capability": _candidate_capability(exercise_type),
        "target_misconception": misconception,
        "focus_tags": [misconception, "state_scope", "runtime_evidence"],
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
        "knowledge_point_id": str(context["id"]),
        "runtime_tier": str(runtime_profile.get("runtime_tier") or "browser_preview"),
        "title": f"{title}: dev review variant {index + 1}",
        "warmup_question": f"先回忆 {title} 里与 {misconception} 相关的风险点。",
        "warmup_expected_focus": "状态生命周期、事件行为和可见证据需要一起判断。",
        "warmup_keywords": ["state", "scope", "event", "evidence", "diff"],
        "review_focus": "用 requirement、diff、可见行为和测试证据判断 AI 代码是否可靠。",
        "estimated_minutes": 8,
    }
    if exercise_type == "review_ai_patch":
        return base | _review_ai_patch_seed(title=title, index=index)
    return base | _practice_review_seed(title=title, exercise_type=exercise_type, index=index)


def _candidate_capability(exercise_type: str) -> str:
    if exercise_type == "fix_bug":
        return "debugging"
    if exercise_type == "explain_code":
        return "concept_explanation"
    if exercise_type == "review_ai_patch":
        return "transfer_or_review"
    return "basic_application"


def _practice_review_seed(*, title: str, exercise_type: str, index: int) -> dict[str, object]:
    increment = index + 1
    starter_code = (
        f"// dev seeded review variant {increment}\n"
        "const button = document.querySelector(\"#counter-button\");\n"
        "const output = document.querySelector(\"#counter-output\");\n"
        f"let count = {index % 2};\n"
        "button.addEventListener(\"click\", () => {\n"
        "  __BLANK_1__;\n"
        "  output.textContent = String(count);\n"
        "});\n"
    )
    placeholder = "count += 1"
    return {
        "prompt_markdown": f"围绕 **{title}** 完成 dev 复习变体 {increment}，并说明为什么状态需要跨事件保留。",
        "starter_code": starter_code,
        "visible_test_policy": "visible_and_hidden_summary",
        "requires_explanation": True,
        "metadata": {
            "required_patterns": ["addEventListener", "count += 1", "output.textContent"],
            "preview_html": {
                "success": "<button id=\"counter-button\">Clicked</button><p id=\"counter-output\">1</p>",
                "failure": "<button id=\"counter-button\">Clicked</button><p id=\"counter-output\">0</p>",
            },
            "selection_reason": f"Use {exercise_type} to check state scope and evidence for {title}.",
            "is_core": index % 2 == 0,
        },
        "code_blanks": [
            {
                "blank_key": "blank_1",
                "placeholder": placeholder,
                "expected_concept": "跨事件复用同一个 count 状态。",
                "acceptable_patterns_json": [{"type": "literal", "value": placeholder}],
                "is_core": True,
                "order_index": 0,
            }
        ],
        "test_cases": [
            _visible_case({"event": "click"}, {"textContent": "1"}, order_index=0),
            _preview_case({"selector": "#counter-output"}, {"textContent": "1"}, order_index=1),
        ],
    }


def _review_ai_patch_seed(*, title: str, index: int) -> dict[str, object]:
    original_code = (
        "const button = document.querySelector(\"#counter-button\");\n"
        "const output = document.querySelector(\"#counter-output\");\n"
        "let count = 0;\n"
        "button.addEventListener(\"click\", () => {\n"
        "  count += 1;\n"
        "  output.textContent = String(count);\n"
        "});\n"
    )
    ai_diff = (
        f"-let count = 0;\n"
        " button.addEventListener(\"click\", () => {\n"
        f"+  let count = {index};\n"
        "   count += 1;\n"
    )
    return {
        "prompt_markdown": f"审核 AI 对 **{title}** 的 dev patch：判断是否破坏连续点击计数。",
        "starter_code": original_code,
        "visible_test_policy": "visible_only",
        "requires_explanation": True,
        "metadata": {
            "requirement": "连续点击按钮时，计数必须持续累加并显示在输出节点中。",
            "original_code": original_code,
            "ai_diff": ai_diff,
            "review_focus": "状态作用域不能被移动到每次事件回调内部。",
            "expected_risk": "count 被移进回调后，每次点击都会重新初始化，连续点击不会累加。",
            "expected_verdict": "fail",
            "expected_next_action": "request_change",
            "selection_reason": f"Review an AI patch to verify evidence quality for {title}.",
            "is_core": True,
        },
        "rubric": {
            "verdict_correctness": "0-2",
            "evidence_grounding": "0-2",
            "knowledge_point_alignment": "0-2",
            "actionability": "0-2",
        },
        "code_blanks": [],
        "test_cases": [],
    }


def _visible_case(input_json: Mapping[str, object], expected_output_json: Mapping[str, object], *, order_index: int) -> dict[str, object]:
    return {
        "case_type": "visible",
        "input_json": dict(input_json),
        "expected_output_json": dict(expected_output_json),
        "assertion_code": None,
        "weight": 1,
        "is_critical": True,
        "timeout_ms": 5000,
        "order_index": order_index,
    }


def _preview_case(input_json: Mapping[str, object], expected_output_json: Mapping[str, object], *, order_index: int) -> dict[str, object]:
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset and seed deterministic local Aearn test data.")
    parser.add_argument("--bootstrap-file", type=Path, default=None, help="Optional desktop dev bootstrap JSON output path.")
    args = parser.parse_args()
    bootstrap_file = resolve_bootstrap_file_path(args.bootstrap_file) if args.bootstrap_file is not None else None
    result = seed_test_data(bootstrap_file=bootstrap_file)
    print(json.dumps({key: result[key] for key in ("userId", "planId", "summary")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
