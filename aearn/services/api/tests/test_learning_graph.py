"""Tests for LangGraph learning conversation state machine."""
from __future__ import annotations

from app.agents.learning_graph import (
    AgentState,
    build_learning_graph,
    compile_learning_graph,
    concept_check,
    concept_intro,
    concept_repair,
    context_assembler,
    persist_side_effects,
    practice_offer,
    route_after_check,
    route_after_context,
    route_after_repair,
    select_exercise,
)


class TestNodeFunctions:
    def test_context_assembler_sets_current_node(self):
        state: AgentState = {"user_id": "u1", "session_id": "s1"}
        result = context_assembler(state)
        assert result["current_node"] == "context_assembler"

    def test_concept_intro_sets_stage(self):
        state: AgentState = {"learning_stage": "concept_intro"}
        result = concept_intro(state)
        assert result["learning_stage"] == "concept_intro"

    def test_concept_check_increments_attempts(self):
        state: AgentState = {"learning_stage_state": {"concept_check_attempts": 1}}
        result = concept_check(state)
        assert result["learning_stage_state"]["concept_check_attempts"] == 2

    def test_concept_repair_sets_stage(self):
        state: AgentState = {}
        result = concept_repair(state)
        assert result["learning_stage"] == "concept_repair"

    def test_practice_offer_sets_unlock_reason(self):
        state: AgentState = {"learning_stage_state": {}}
        result = practice_offer(state)
        assert result["learning_stage_state"]["practice_unlock_reason"] == "concept_check_passed"

    def test_practice_offer_preserves_existing_reason(self):
        state: AgentState = {"learning_stage_state": {"practice_unlock_reason": "concept_check_skipped"}}
        result = practice_offer(state)
        assert result["learning_stage_state"]["practice_unlock_reason"] == "concept_check_skipped"

    def test_select_exercise_sets_practice_stage(self):
        state: AgentState = {}
        result = select_exercise(state)
        assert result["learning_stage"] == "practice_support"

    def test_persist_side_effects_clears_queue(self):
        state: AgentState = {"side_effects": [{"type": "update_stage"}]}
        result = persist_side_effects(state)
        assert result["side_effects"] == []


class TestRoutingFunctions:
    def test_route_after_context_default_to_intro(self):
        state: AgentState = {"learning_stage": "concept_intro"}
        assert route_after_context(state) == "concept_intro"

    def test_route_after_context_practice_stage(self):
        state: AgentState = {"learning_stage": "practice_support"}
        assert route_after_context(state) == "select_exercise"

    def test_route_after_context_check_stage(self):
        state: AgentState = {"learning_stage": "concept_check"}
        assert route_after_context(state) == "concept_check"

    def test_route_after_check_correct(self):
        state: AgentState = {"learning_stage_state": {"concept_check_result": "correct"}}
        assert route_after_check(state) == "practice_offer"

    def test_route_after_check_incorrect_under_limit(self):
        state: AgentState = {"learning_stage_state": {"concept_check_result": "incorrect", "concept_check_attempts": 1}}
        assert route_after_check(state) == "concept_repair"

    def test_route_after_check_incorrect_at_limit(self):
        state: AgentState = {"learning_stage_state": {"concept_check_result": "incorrect", "concept_check_attempts": 3}}
        assert route_after_check(state) == "practice_offer"

    def test_route_after_repair_correct(self):
        state: AgentState = {"learning_stage_state": {"concept_check_result": "correct"}}
        assert route_after_repair(state) == "practice_offer"

    def test_route_after_repair_still_wrong_under_limit(self):
        state: AgentState = {"learning_stage_state": {"concept_check_result": "incorrect", "concept_check_attempts": 2}}
        assert route_after_repair(state) == "concept_check"

    def test_route_after_repair_at_limit(self):
        state: AgentState = {"learning_stage_state": {"concept_check_result": "incorrect", "concept_check_attempts": 3}}
        assert route_after_repair(state) == "practice_offer"


class TestGraphStructure:
    def test_graph_builds_without_error(self):
        graph = build_learning_graph()
        assert graph is not None

    def test_graph_compiles(self):
        compiled = compile_learning_graph()
        assert compiled is not None

    def test_graph_has_expected_nodes(self):
        graph = build_learning_graph()
        node_names = set(graph.nodes.keys())
        expected = {"context_assembler", "concept_intro", "concept_check", "concept_repair", "practice_offer", "select_exercise", "persist_side_effects"}
        assert expected.issubset(node_names)

    def test_graph_executes_simple_path(self):
        compiled = compile_learning_graph()
        initial_state: AgentState = {
            "user_id": "test-user",
            "session_id": "test-session",
            "learning_stage": "concept_intro",
            "learning_stage_state": {"concept_check_result": "correct", "concept_check_attempts": 0},
            "side_effects": [],
            "messages": [],
            "errors": [],
        }
        result = compiled.invoke(initial_state)
        assert result["current_node"] == "persist_side_effects"
        assert result["side_effects"] == []
