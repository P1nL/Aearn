from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.agents.agent_runtime_context import (
    build_runtime_context_block,
    limit_text,
    safe_messages_from_records,
    sanitize_summary_list,
    sanitize_summary_text,
)


def build_onboarding_conversation_runtime_context(
    *,
    extracted_context: Mapping[str, object],
    history: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    safe_summary = {
        "goal_text": sanitize_summary_text(extracted_context.get("goal_text"), max_length=360),
        "language": sanitize_summary_text(extracted_context.get("language"), max_length=80),
        "target_level": sanitize_summary_text(extracted_context.get("target_level"), max_length=80),
        "time_budget": _time_budget_text(extracted_context.get("time_budget")),
        "known_preferences": sanitize_summary_list(
            [
                extracted_context.get("focus"),
                extracted_context.get("profession"),
                extracted_context.get("background_context"),
            ],
            max_item_length=160,
        ),
        "missing_slots": _missing_onboarding_slots(extracted_context),
        "rejected_directions": sanitize_summary_list(extracted_context.get("rejected_directions")),
        "current_plan_draft_status": "stashed" if isinstance(extracted_context.get("plan_draft"), Mapping) else "none",
        "recommended_next_question": _recommended_onboarding_question(extracted_context),
        "summary_confidence": "medium" if extracted_context.get("plan_ready") else "low",
    }
    safe_messages = [message.as_dict() for message in safe_messages_from_records(history)][-4:]
    return build_runtime_context_block(
        safe_summary=safe_summary,
        recent_messages=safe_messages,
        current_focus_key="recommended_next_question",
        fallback_focus_key="goal_text",
        avoid_key="rejected_directions",
    )


def build_onboarding_plan_runtime_context(
    *,
    goal_text: str,
    mode: str,
    user_profile: Mapping[str, object],
    course: Mapping[str, object],
    materials: Sequence[Mapping[str, object]],
    clarification_answers: Sequence[Mapping[str, object]],
    deterministic_plan_draft: Mapping[str, object],
) -> dict[str, object]:
    safe_summary = {
        "goal_text": sanitize_summary_text(goal_text, max_length=360),
        "language": sanitize_summary_text(
            deterministic_plan_draft.get("language") or course.get("language"),
            max_length=80,
        ),
        "target_level": sanitize_summary_text(deterministic_plan_draft.get("target_level"), max_length=80),
        "time_budget": "",
        "known_preferences": _known_profile_preferences(user_profile),
        "missing_slots": [],
        "rejected_directions": [],
        "current_plan_draft_status": "server_template_ready",
        "recommended_next_question": _recommended_plan_note(
            mode=mode,
            materials=materials,
            clarification_answers=clarification_answers,
        ),
        "summary_confidence": "medium",
    }
    return build_runtime_context_block(
        safe_summary=safe_summary,
        recent_messages=[],
        current_focus_key="recommended_next_question",
        fallback_focus_key="goal_text",
        avoid_key="rejected_directions",
    )


def build_review_runtime_context(
    *,
    knowledge_point_id: str,
    knowledge_point_title: str,
    weak_points: Sequence[str],
    due_at: str | None,
    forget_risk: str,
    last_fsrs_rating: str | None,
    latest_attempt: Mapping[str, object] | None,
) -> dict[str, object]:
    latest_facts = _latest_visible_attempt_facts(latest_attempt)
    safe_summary = {
        "review_goal": sanitize_summary_text(knowledge_point_title, max_length=180),
        "due_reason": sanitize_summary_text(
            f"due_at={due_at or 'unknown'}; forget_risk={forget_risk}; last_fsrs_rating={last_fsrs_rating or 'unknown'}",
            max_length=260,
        ),
        "weak_points": sanitize_summary_list(weak_points, max_item_length=120),
        "latest_visible_attempt_facts": latest_facts,
        "variant_rationale": sanitize_summary_text(
            _review_variant_rationale(weak_points=weak_points, latest_facts=latest_facts),
            max_length=220,
        ),
        "recommended_review_strategy": sanitize_summary_text(
            "先复述薄弱点，再用变体题验证能否独立完成。",
            max_length=160,
        ),
        "summary_confidence": "medium" if latest_facts or weak_points else "low",
    }
    return build_runtime_context_block(
        safe_summary=safe_summary,
        recent_messages=[],
        current_focus_key="due_reason",
        strategy_key="recommended_review_strategy",
        avoid_key="weak_points",
    ) | {"knowledge_point_id": knowledge_point_id}


def _missing_onboarding_slots(extracted_context: Mapping[str, object]) -> list[str]:
    missing: list[str] = []
    for key in ("language", "target_level", "goal_text"):
        if not str(extracted_context.get(key) or "").strip():
            missing.append(key)
    return missing


def _recommended_onboarding_question(extracted_context: Mapping[str, object]) -> str:
    missing = _missing_onboarding_slots(extracted_context)
    if not missing:
        return "信息已够生成路线卡片，如需修改只追问时间、方向或难度。"
    next_slot = missing[0]
    if next_slot == "language":
        return "先确认用户想学哪门编程语言。"
    if next_slot == "target_level":
        return "先确认用户当前基础水平。"
    return "先确认用户的具体学习目标。"


def _time_budget_text(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    minutes = value.get("minutes_per_day")
    days = value.get("days_per_week")
    if minutes is None and days is None:
        return ""
    return limit_text(f"{minutes or '?'} minutes/day, {days or '?'} days/week", 120)


def _known_profile_preferences(user_profile: Mapping[str, object]) -> list[str]:
    keys = (
        "learning_style",
        "teaching_preference",
        "encouragement_preference",
        "profession",
        "background_context",
    )
    return sanitize_summary_list([user_profile.get(key) for key in keys], max_item_length=160)


def _recommended_plan_note(
    *,
    mode: str,
    materials: Sequence[Mapping[str, object]],
    clarification_answers: Sequence[Mapping[str, object]],
) -> str:
    if clarification_answers:
        return "用澄清答案微调路线，但保持 server-owned template 字段不变。"
    if mode == "material_based" or materials:
        return "用用户资料调整重点，但不能新增模板外知识点或运行时承诺。"
    return "围绕目标生成路线，保留课程模板和 PlanDraft validation 权威性。"


def _latest_visible_attempt_facts(latest_attempt: Mapping[str, object] | None) -> list[str]:
    if latest_attempt is None:
        return []
    facts: list[str] = []
    for key in (
        "attempt_type",
        "runtime_status",
        "test_pass_rate",
        "passed_test_count",
        "total_test_count",
        "error_cause",
        "score",
        "fsrs_rating",
    ):
        value = latest_attempt.get(key)
        if value is not None and str(value).strip():
            facts.append(sanitize_summary_text(f"{key}={value}", max_length=120))
    return [fact for fact in facts if fact][:8]


def _review_variant_rationale(*, weak_points: Sequence[str], latest_facts: Sequence[str]) -> str:
    if weak_points:
        return f"优先检查薄弱点：{', '.join(str(item) for item in weak_points[:3])}"
    if latest_facts:
        return "基于最近一次可见 attempt 事实选择同构变体。"
    return "基于当前到期复习项选择基础变体。"
