"""Tests for agent routing and handoff logic."""
from __future__ import annotations

from app.agents.graphs.router import (
    build_routing_context,
    get_agent_description,
    get_handoff_targets,
    route_message,
)


class TestRouteMessage:
    def test_teaching_stage_routes_to_teaching(self):
        result = route_message(session_stage="concept_intro", user_message="什么是变量？")
        assert result == "teaching"

    def test_concept_qna_routes_to_teaching(self):
        result = route_message(session_stage="concept_qna", user_message="我还是不太明白")
        assert result == "teaching"

    def test_diagnosis_stage_routes_to_diagnosis(self):
        result = route_message(session_stage="concept_check", user_message="我觉得答案是A")
        assert result == "diagnosis"

    def test_concept_repair_routes_to_diagnosis(self):
        result = route_message(session_stage="concept_repair", user_message="让我再试一次")
        assert result == "diagnosis"

    def test_practice_stage_routes_to_exercise_coach(self):
        result = route_message(session_stage="practice_support", user_message="这个报错是什么意思")
        assert result == "exercise_coach"

    def test_practice_with_explain_routes_to_teaching(self):
        result = route_message(session_stage="practice_support", user_message="为什么要用return？")
        assert result == "teaching"

    def test_practice_with_repeated_runtime_error_routes_to_diagnosis(self):
        result = route_message(
            session_stage="practice_support",
            user_message="这个错误为什么一直出现？",
            latest_attempt={"runtime_status": "runtime_error", "error_count": 2},
        )
        assert result == "diagnosis"

    def test_teaching_with_practice_keyword_routes_to_exercise(self):
        result = route_message(session_stage="concept_intro", user_message="我想做练习")
        assert result == "exercise_coach"

    def test_explicit_code_request_with_tool_context_routes_to_exercise(self):
        result = route_message(
            session_stage="concept_qna",
            user_message="我想直接写代码试一下",
            tool_context={"exercise_available": True},
        )
        assert result == "exercise_coach"

    def test_repeated_confusion_with_profile_weak_signal_routes_to_diagnosis(self):
        result = route_message(
            session_stage="concept_qna",
            user_message="我又卡在这里了",
            learner_profile_summary="【学习者画像】已确认薄弱点: closures | 常见错误模式: off_by_one(×3)",
        )
        assert result == "diagnosis"

    def test_review_session_routes_to_review_coach(self):
        result = route_message(session_stage="concept_intro", user_message="hello", session_type="review")
        assert result == "review_coach"

    def test_unknown_stage_defaults_to_teaching(self):
        result = route_message(session_stage="unknown_stage", user_message="hi")
        assert result == "teaching"


class TestHandoffTargets:
    def test_teaching_can_handoff_to_exercise_and_diagnosis(self):
        targets = get_handoff_targets("teaching")
        assert "exercise_coach" in targets
        assert "diagnosis" in targets

    def test_exercise_coach_can_handoff_to_teaching(self):
        targets = get_handoff_targets("exercise_coach")
        assert "teaching" in targets

    def test_unknown_agent_returns_empty(self):
        targets = get_handoff_targets("nonexistent")
        assert targets == []


class TestRoutingContext:
    def test_builds_context_with_targets(self):
        context = build_routing_context("teaching", ["exercise_coach", "diagnosis"])
        assert "exercise_coach" in context
        assert "diagnosis" in context
        assert "转交" in context

    def test_empty_targets_returns_empty(self):
        context = build_routing_context("teaching", [])
        assert context == ""


class TestAgentDescriptions:
    def test_known_agents_have_descriptions(self):
        for name in ["teaching", "exercise_coach", "diagnosis", "review_coach"]:
            desc = get_agent_description(name)
            assert len(desc) > 10

    def test_unknown_agent_has_fallback(self):
        desc = get_agent_description("unknown")
        assert "General" in desc
