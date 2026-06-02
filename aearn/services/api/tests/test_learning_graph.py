"""Tests for LangGraph learning conversation state machine."""
from __future__ import annotations

import app.agents.graphs.learning_graph as learning_graph_module
import app.services.conversations.learning_conversation as learning_conversation_service
from app.agents.graphs.graph_runtime_contracts import (
    GraphRunResult,
    IntentType,
    build_run_result,
    build_graph_memory_snapshot,
    build_graph_rag_context,
    make_intent,
)
from app.agents.graphs.learning_graph import (
    AgentState,
    build_learning_graph,
    compile_learning_graph,
    concept_check,
    concept_intro,
    concept_repair,
    context_assembler,
    graph_result_to_run_result,
    invoke_orchestration,
    persist_side_effects,
    practice_offer,
    route_after_check,
    route_after_context,
    route_after_repair,
    select_exercise,
)
from app.services.conversations.learning_conversation import LearningConversationContext, build_learning_graph_state


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

    def test_service_state_builder_includes_memory_and_rag_context(self):
        memory_snapshot = build_graph_memory_snapshot(profile_summary="已确认薄弱点: closures").to_dict()
        rag_context = build_graph_rag_context(
            knowledge_point_id="kp1",
            query="closures",
            chunks=[
                {
                    "chunk_id": "chunk1",
                    "chunk_type": "outline",
                    "title": "Closures",
                    "content": "Use closures to keep shared state.",
                }
            ],
        ).to_dict()
        context = LearningConversationContext(
            session_id="s1",
            user_id="u1",
            knowledge_point_id="kp1",
            current_stage="DOM events",
            learning_stage="concept_intro",
            learning_stage_state={},
            knowledge_point={"id": "kp1", "title": "事件监听"},
            lesson_outline=[],
            lesson_sources=[],
            exercise=None,
            latest_attempt=None,
            learner_profile_summary="已确认薄弱点: closures",
            conversation_context={},
            graph_memory_snapshot=memory_snapshot,
            rag_context=rag_context,
        )

        state = build_learning_graph_state(context, user_content="为什么要用闭包？")

        assert state["memory_snapshot"] == memory_snapshot
        assert state["rag_context"] == rag_context
        assert state["rag_context"]["knowledge_point_id"] == "kp1"


class TestOrchestrationGraph:
    """Tests for the orchestration graph that replaces _determine_transition."""

    def _base_input(self, **overrides):
        defaults = {
            "session_id": "s1",
            "user_id": "u1",
            "learning_stage": "concept_check",
            "learning_stage_state": {},
            "user_text": "A",
            "knowledge_point": {"id": "kp1", "title": "事件绑定"},
            "lesson_outline": [
                {"id": "sp1", "title": "事件监听", "note": "addEventListener"},
                {"id": "sp2", "title": "状态共享", "note": "闭包变量"},
            ],
        }
        defaults.update(overrides)
        return defaults

    def test_practice_support_stays(self):
        result = invoke_orchestration(**self._base_input(
            learning_stage="practice_support",
            user_text="我的代码报错了",
        ))
        assert result["next_stage"] == "practice_support"
        assert result["tool_name"] is None

    def test_history_request(self):
        result = invoke_orchestration(**self._base_input(
            learning_stage="concept_intro",
            user_text="我想看历史对话",
        ))
        assert result["tool_name"] == "show_learning_history"

    def test_practice_request_from_concept_check(self):
        result = invoke_orchestration(**self._base_input(
            learning_stage="concept_check",
            user_text="我想先开始练习",
        ))
        assert result["next_stage"] == "practice_support"
        assert result["tool_name"] == "show_code_exercise"
        assert result["tool_names"] == ["show_concept_check_result", "show_code_exercise"]
        assert result["next_state"]["practice_unlock_reason"] == "concept_check_skipped"
        assert result["next_state"]["concept_check_result"] == "skipped"
        assert result["human_checkpoint"]["checkpoint_type"] == "approval"
        assert result["human_checkpoint"]["reason"] == "concept_check_skipped"
        run_result = result["run_result"]
        assert isinstance(run_result, GraphRunResult)
        assert run_result.next_stage == "practice_support"
        assert any(
            intent.intent_type == IntentType.STAGE_UPDATE
            and intent.target == "learning_session"
            for intent in run_result.intents
        )
        tool_targets = [
            intent.target
            for intent in run_result.intents
            if intent.intent_type == IntentType.TOOL_CALL
        ]
        assert tool_targets == ["show_concept_check_result", "show_code_exercise"]
        checkpoint_intent = next(
            intent for intent in run_result.intents if intent.intent_type == IntentType.FEEDBACK_REQUEST
        )
        assert checkpoint_intent.target == "human_checkpoint"
        assert checkpoint_intent.payload["checkpoint_type"] == "approval"

    def test_practice_request_from_practice_offer(self):
        result = invoke_orchestration(**self._base_input(
            learning_stage="practice_offer",
            user_text="开始练习",
        ))
        assert result["next_stage"] == "practice_support"
        assert result["tool_name"] == "show_code_exercise"
        assert result["next_state"]["practice_unlock_reason"] == "concept_check_passed"

    def test_concept_check_answer(self):
        result = invoke_orchestration(**self._base_input(
            learning_stage="concept_check",
            user_text="选A，因为变量在回调外面",
        ))
        assert result["next_stage"] == "concept_check"
        assert result["tool_name"] == "show_concept_check_result"
        assert result["learner_content"] == "选A，因为变量在回调外面"

    def test_concept_repair_answer(self):
        result = invoke_orchestration(**self._base_input(
            learning_stage="concept_repair",
            user_text="不能，它会重新开始",
        ))
        assert result["next_stage"] == "concept_repair"
        assert result["tool_name"] == "show_concept_check_result"

    def test_concept_intro_question(self):
        result = invoke_orchestration(**self._base_input(
            learning_stage="concept_intro",
            user_text="为什么要用闭包？",
        ))
        assert result["next_stage"] == "concept_qna"
        assert result["tool_name"] is None

    def test_concept_intro_concept_help(self):
        result = invoke_orchestration(**self._base_input(
            learning_stage="concept_intro",
            user_text="给我例子",
        ))
        assert result["next_stage"] == "concept_qna"
        assert result["tool_name"] is None

    def test_concept_intro_statement_goes_to_readiness(self):
        result = invoke_orchestration(**self._base_input(
            learning_stage="concept_intro",
            user_text="我觉得事件绑定就是把函数挂到元素上",
        ))
        assert result["next_stage"] == "readiness_check"
        assert result["tool_name"] is None

    def test_readiness_check_feynman_pass(self):
        result = invoke_orchestration(**self._base_input(
            learning_stage="readiness_check",
            user_text="因为事件绑定会把回调函数连接到 DOM 元素，状态变量放在回调外面所以多次触发会共享同一个值",
        ))
        assert result["next_stage"] == "practice_support"
        assert result["tool_name"] == "show_code_exercise"
        assert result["next_state"]["feynman_status"] == "passed"

    def test_readiness_check_feynman_fail(self):
        result = invoke_orchestration(**self._base_input(
            learning_stage="readiness_check",
            user_text="不太确定",
        ))
        assert result["next_stage"] == "readiness_check"
        assert result["tool_name"] == "show_learning_history"
        assert result["next_state"]["feynman_status"] == "failed"
        assert result["human_checkpoint"]["checkpoint_type"] == "clarification"
        assert result["human_checkpoint"]["reason"] == "feynman_readiness_unclear"

    def test_direct_answer_request_emits_safety_checkpoint(self):
        result = invoke_orchestration(**self._base_input(
            learning_stage="concept_intro",
            user_text="直接给我完整代码和标准答案",
        ))
        assert result["next_stage"] == "concept_intro"
        assert result["tool_name"] is None
        assert result["human_checkpoint"]["checkpoint_type"] == "safety"
        assert result["human_checkpoint"]["reason"] == "direct_answer_request"
        run_result = result["run_result"]
        checkpoint_intent = next(
            intent for intent in run_result.intents if intent.intent_type == IntentType.FEEDBACK_REQUEST
        )
        assert checkpoint_intent.target == "human_checkpoint"
        assert checkpoint_intent.payload["scope"] == "teaching_safety"

    def test_repair_limit_sets_correct_unlock_reason(self):
        result = invoke_orchestration(**self._base_input(
            learning_stage="concept_check",
            learning_stage_state={"concept_check_attempts": 2, "repair_limit_reached": True},
            user_text="开始练习",
        ))
        assert result["next_state"]["practice_unlock_reason"] == "concept_check_repair_limit"
        assert result["tool_names"] == ["show_concept_check_result", "show_code_exercise"]

    def test_subpoint_ids_populated(self):
        result = invoke_orchestration(**self._base_input(
            learning_stage="concept_check",
            user_text="A",
        ))
        assert result["next_state"]["covered_subpoint_ids"] == ["sp1", "sp2"]

    def test_concept_summary_populated(self):
        result = invoke_orchestration(**self._base_input(
            learning_stage="concept_check",
            user_text="A",
        ))
        assert "事件监听" in result["next_state"]["concept_summary"]
        assert "状态共享" in result["next_state"]["concept_summary"]

    def test_invoke_orchestration_passes_thread_config(self, monkeypatch):
        captured: dict[str, object] = {}

        class FakeCompiledGraph:
            def invoke(self, state, config=None):  # type: ignore[no-untyped-def]
                captured["state"] = state
                captured["config"] = config
                return {
                    "next_stage": "concept_qna",
                    "tool_name": None,
                    "learner_content": "",
                    "next_state": state["learning_stage_state"],
                }

        monkeypatch.setattr(
            learning_graph_module,
            "compile_orchestration_graph",
            lambda: FakeCompiledGraph(),
        )

        result = invoke_orchestration(**self._base_input(
            session_id="session-123",
            user_id="user-456",
            learning_stage="concept_intro",
            user_text="为什么要用闭包？",
        ))

        config = captured["config"]
        assert isinstance(config, dict)
        assert config["configurable"]["thread_id"] == "aearn:learning:session-123"
        assert config["configurable"]["checkpoint_ns"] == "learning_orchestration"
        assert config["metadata"]["durable_state_owner"] == "service"
        assert result["next_stage"] == "concept_qna"

    def test_invoke_orchestration_passes_memory_and_rag_context(self, monkeypatch):
        captured: dict[str, object] = {}
        memory_snapshot = build_graph_memory_snapshot(profile_summary="已确认薄弱点: closures").to_dict()
        rag_context = build_graph_rag_context(
            knowledge_point_id="kp1",
            query="closures",
            chunks=[
                {
                    "chunk_id": "chunk1",
                    "chunk_type": "outline",
                    "title": "Closures",
                    "content": "Closures keep access to outer state.",
                }
            ],
        ).to_dict()

        class FakeCompiledGraph:
            def invoke(self, state, config=None):  # type: ignore[no-untyped-def]
                del config
                captured["state"] = state
                return {
                    "next_stage": "concept_qna",
                    "tool_name": None,
                    "learner_content": "",
                    "next_state": state["learning_stage_state"],
                }

        monkeypatch.setattr(
            learning_graph_module,
            "compile_orchestration_graph",
            lambda: FakeCompiledGraph(),
        )

        result = invoke_orchestration(
            **self._base_input(
                learning_stage="concept_intro",
                user_text="为什么要用闭包？",
            ),
            memory_snapshot=memory_snapshot,
            rag_context=rag_context,
        )

        state = captured["state"]
        assert isinstance(state, dict)
        assert state["memory_snapshot"] == memory_snapshot
        assert state["rag_context"] == rag_context
        assert result["next_stage"] == "concept_qna"

    def test_graph_result_to_run_result_sanitizes_human_checkpoint(self):
        run_result = graph_result_to_run_result({
            "next_stage": "concept_intro",
            "next_state": {},
            "human_checkpoint": {
                "checkpoint_id": "cp1",
                "checkpoint_type": "safety",
                "reason": "direct_answer_request",
                "prompt": "provider payload contains api key",
                "scope": "teaching_safety",
                "metadata": {"api_key": "sk-secret", "current_stage": "concept_intro"},
            },
        })

        checkpoint_intent = next(
            intent for intent in run_result.intents if intent.intent_type == IntentType.FEEDBACK_REQUEST
        )
        assert checkpoint_intent.target == "human_checkpoint"
        assert "REDACTED" in checkpoint_intent.payload["prompt"]
        assert checkpoint_intent.payload["metadata"]["api_key"] == "[REDACTED]"


class TestLearningServiceGraphBoundary:
    def _context(self, **overrides):
        defaults = {
            "session_id": "s1",
            "user_id": "u1",
            "knowledge_point_id": "kp1",
            "current_stage": "事件绑定",
            "learning_stage": "concept_check",
            "learning_stage_state": {"concept_check_attempts": 1},
            "knowledge_point": {"id": "kp1", "title": "事件绑定"},
            "lesson_outline": [{"id": "sp1", "title": "事件监听", "note": "addEventListener"}],
            "lesson_sources": [],
            "exercise": None,
            "latest_attempt": None,
            "learner_profile_summary": "",
            "conversation_context": {},
            "graph_memory_snapshot": {"available": True, "profile_summary": "prefers examples"},
            "rag_context": {
                "knowledge_point_id": "kp1",
                "retrieval_status": "available",
                "chunks": [{"chunk_id": "chunk1", "content": "Use event listeners."}],
            },
        }
        defaults.update(overrides)
        return LearningConversationContext(**defaults)

    def test_service_consumes_ordered_graph_stage_and_tool_intents(self, monkeypatch):
        next_state = {
            "covered_subpoint_ids": ["sp1"],
            "practice_unlock_reason": "concept_check_skipped",
            "concept_check_result": "skipped",
            "learning_incomplete": True,
        }

        def fake_invoke_orchestration(**kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return {
                "run_result": build_run_result(
                    next_stage="practice_support",
                    intents=[
                        make_intent(
                            IntentType.STAGE_UPDATE,
                            "learning_session",
                            {
                                "learning_stage": "practice_support",
                                "learning_stage_state": next_state,
                                "learner_content": "开始练习",
                            },
                        ),
                        make_intent(
                            IntentType.TOOL_CALL,
                            "show_concept_check_result",
                            {"learner_content": "开始练习"},
                        ),
                        make_intent(
                            IntentType.FEEDBACK_REQUEST,
                            "human_checkpoint",
                            {"checkpoint_type": "approval", "reason": "concept_check_skipped"},
                        ),
                        make_intent(
                            IntentType.TOOL_CALL,
                            "show_code_exercise",
                            {"learner_content": "开始练习"},
                        ),
                    ],
                ),
            }

        monkeypatch.setattr(
            learning_conversation_service,
            "invoke_orchestration",
            fake_invoke_orchestration,
        )

        transition = learning_conversation_service._determine_transition_via_graph(
            self._context(),
            "开始练习",
        )

        assert transition.learning_stage == "practice_support"
        assert transition.learning_stage_state == next_state
        assert transition.tool_names == ("show_concept_check_result", "show_code_exercise")
        assert transition.tool_name == "show_code_exercise"
        assert transition.learner_content == "开始练习"

    def test_service_rejects_unscoped_graph_intent_and_uses_imperative_fallback(self, monkeypatch):
        def fake_invoke_orchestration(**kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return {
                "run_result": build_run_result(
                    next_stage="practice_support",
                    intents=[
                        make_intent(
                            IntentType.STAGE_UPDATE,
                            "learning_session",
                            {
                                "learning_stage": "practice_support",
                                "learning_stage_state": {"unsafe_graph_write": True},
                            },
                        ),
                        make_intent(
                            IntentType.PERSISTENCE,
                            "attempts",
                            {"unsafe_graph_write": True},
                        ),
                    ],
                ),
            }

        monkeypatch.setattr(
            learning_conversation_service,
            "invoke_orchestration",
            fake_invoke_orchestration,
        )

        transition = learning_conversation_service._determine_transition_via_graph(
            self._context(learning_stage="concept_intro", learning_stage_state={}),
            "我想看历史对话",
        )

        assert transition.learning_stage == "concept_intro"
        assert transition.learning_stage_state == {}
        assert transition.tool_name == "show_learning_history"
        assert "unsafe_graph_write" not in transition.learning_stage_state

    def test_service_passes_memory_and_rag_context_to_graph(self, monkeypatch):
        captured: dict[str, object] = {}

        def fake_invoke_orchestration(**kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return {
                "run_result": build_run_result(
                    next_stage="concept_qna",
                    intents=[
                        make_intent(
                            IntentType.STAGE_UPDATE,
                            "learning_session",
                            {
                                "learning_stage": "concept_qna",
                                "learning_stage_state": {"graph_owned": True},
                            },
                        ),
                    ],
                ),
            }

        context = self._context()
        monkeypatch.setattr(
            learning_conversation_service,
            "invoke_orchestration",
            fake_invoke_orchestration,
        )

        transition = learning_conversation_service._determine_transition_via_graph(
            context,
            "为什么要用事件监听？",
        )

        assert captured["memory_snapshot"] == context.graph_memory_snapshot
        assert captured["rag_context"] == context.rag_context
        assert transition.learning_stage == "concept_qna"
        assert transition.learning_stage_state == {"graph_owned": True}
