"""Tests for review graph orchestration."""
from __future__ import annotations

from app.agents.graphs.review_graph import (
    invoke_review_orchestration,
    review_error_to_fallback,
    review_result_to_run_result,
)


class TestReviewOrchestration:
    def test_start_when_due(self):
        result = invoke_review_orchestration(
            user_id="u1",
            knowledge_point_id="kp1",
            action="start",
            is_due=True,
            has_active_session=False,
        )
        assert result["next_action"] == "start_session"
        assert result["intent_type"] == "persistence"
        assert result["intent_payload"]["target"] == "review_session"

    def test_start_reuses_active_session(self):
        result = invoke_review_orchestration(
            session_id="s1",
            user_id="u1",
            knowledge_point_id="kp1",
            action="start",
            is_due=True,
            has_active_session=True,
        )
        assert result["next_action"] == "reuse_session"
        assert result["intent_payload"]["session_id"] == "s1"

    def test_start_rejects_not_due(self):
        result = invoke_review_orchestration(
            user_id="u1",
            knowledge_point_id="kp1",
            action="start",
            is_due=False,
        )
        assert result["next_action"] == "reject_not_due"
        assert result["intent_type"] == "none"

    def test_submit_routes_to_review_batch(self):
        result = invoke_review_orchestration(
            session_id="s1",
            user_id="u1",
            knowledge_point_id="kp1",
            action="submit",
            attempt_result="passed",
            fsrs_rating="Good",
        )
        assert result["next_action"] == "submit_review_batch"
        assert result["intent_type"] == "persistence"
        assert result["intent_payload"]["target"] == "review_batch"
        assert result["intent_payload"]["fsrs_rating"] == "Good"

    def test_submit_normalizes_invalid_rating(self):
        result = invoke_review_orchestration(
            session_id="s1",
            user_id="u1",
            knowledge_point_id="kp1",
            action="submit",
            attempt_result="failed",
            fsrs_rating="invalid_rating",
        )
        assert result["intent_payload"]["fsrs_rating"] == "Good"

    def test_warmup_action(self):
        result = invoke_review_orchestration(
            session_id="s1",
            user_id="u1",
            knowledge_point_id="kp1",
            action="warmup",
        )
        assert result["next_action"] == "warmup"
        assert result["intent_type"] == "tool_call"
        assert result["intent_payload"]["tool"] == "evaluate_warmup"

    def test_message_with_coach_feedback(self):
        result = invoke_review_orchestration(
            session_id="s1",
            user_id="u1",
            knowledge_point_id="kp1",
            action="message",
            coach_feedback_requested=True,
        )
        assert result["next_action"] == "coach_feedback"
        assert result["intent_type"] == "tool_call"
        assert result["intent_payload"]["tool"] == "review_coach"

    def test_message_without_coach_continues(self):
        result = invoke_review_orchestration(
            session_id="s1",
            user_id="u1",
            knowledge_point_id="kp1",
            action="message",
            coach_feedback_requested=False,
        )
        assert result["next_action"] == "continue"
        assert result["intent_type"] == "none"

    def test_unknown_action_continues(self):
        result = invoke_review_orchestration(
            user_id="u1",
            knowledge_point_id="kp1",
            action="unknown",
        )
        assert result["next_action"] == "continue"


class TestReviewContractAdapters:
    def test_run_result_from_persistence(self):
        result = {
            "next_action": "submit_review_batch",
            "intent_type": "persistence",
            "intent_payload": {"target": "review_batch", "fsrs_rating": "Good"},
        }
        run_result = review_result_to_run_result(result)
        assert run_result.next_stage == "submit_review_batch"
        assert len(run_result.intents) == 1
        assert run_result.intents[0].intent_type.value == "persistence"

    def test_run_result_from_tool_call(self):
        result = {
            "next_action": "coach_feedback",
            "intent_type": "tool_call",
            "intent_payload": {"tool": "review_coach"},
        }
        run_result = review_result_to_run_result(result)
        assert run_result.next_stage == "coach_feedback"
        assert len(run_result.intents) == 1
        assert run_result.intents[0].intent_type.value == "tool_call"

    def test_run_result_from_no_intent(self):
        result = {
            "next_action": "continue",
            "intent_type": "none",
            "intent_payload": {},
        }
        run_result = review_result_to_run_result(result)
        assert run_result.next_stage == "continue"
        assert len(run_result.intents) == 0

    def test_fallback_redacts_error(self):
        fb = review_error_to_fallback(
            RuntimeError("stack_trace: secret api_key=sk-123"),
            fallback_action="continue",
        )
        assert "internal error" in fb.reason
        assert "sk-123" not in fb.reason
        assert fb.recoverable is True
