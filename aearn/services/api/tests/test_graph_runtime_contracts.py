"""Tests for shared graph runtime contracts."""
from __future__ import annotations

from app.agents.graphs.graph_runtime_contracts import (
    GraphFallback,
    GraphHumanCheckpoint,
    GraphIntent,
    GraphMemorySnapshot,
    GraphRagContext,
    GraphRuntimeLayer,
    GraphRunResult,
    GraphRuntimeState,
    IntentType,
    MAX_HUMAN_CHECKPOINT_PROMPT_LENGTH,
    MAX_PROFILE_SUMMARY_LENGTH,
    MAX_RAG_CHUNKS,
    MAX_RAG_CHUNK_CONTENT_LENGTH,
    MAX_INTENTS_PER_RUN,
    MAX_THREAD_ID_LENGTH,
    MAX_USER_TEXT_LENGTH,
    boundary_rule_for_intent_type,
    build_checkpoint_thread_state,
    build_fallback,
    build_graph_human_checkpoint,
    build_graph_memory_snapshot,
    build_graph_rag_context,
    build_run_result,
    build_runtime_state,
    graph_runtime_boundary_contract,
    make_intent,
    redact_value,
    validate_boundary_intents,
    validate_intents,
    validate_run_result,
    validate_run_result_for_boundary,
)


class TestBuildRuntimeState:
    def test_basic_construction(self):
        state = build_runtime_state(
            session_id="s1",
            user_id="u1",
            session_type="learning",
            current_stage="concept_intro",
            user_text="hello",
        )
        assert isinstance(state, GraphRuntimeState)
        assert state.session_id == "s1"
        assert state.user_id == "u1"
        assert state.session_type == "learning"
        assert state.current_stage == "concept_intro"
        assert state.user_text == "hello"

    def test_bounds_user_text(self):
        long_text = "x" * (MAX_USER_TEXT_LENGTH + 500)
        state = build_runtime_state(
            session_id="s1",
            user_id="u1",
            session_type="learning",
            current_stage="intro",
            user_text=long_text,
        )
        assert len(state.user_text) == MAX_USER_TEXT_LENGTH

    def test_redacts_sensitive_session_facts(self):
        state = build_runtime_state(
            session_id="s1",
            user_id="u1",
            session_type="learning",
            current_stage="intro",
            user_text="hi",
            session_facts={
                "title": "Variables",
                "solution_reference": "def solve(): return 42",
                "hidden_tests": ["assert solve() == 42"],
            },
        )
        assert state.session_facts["title"] == "Variables"
        assert state.session_facts["solution_reference"] == "[REDACTED]"
        assert state.session_facts["hidden_tests"] == "[REDACTED]"

    def test_to_dict(self):
        state = build_runtime_state(
            session_id="s1",
            user_id="u1",
            session_type="learning",
            current_stage="intro",
            user_text="hi",
            scoped_ids={"plan_id": "p1"},
        )
        d = state.to_dict()
        assert d["session_id"] == "s1"
        assert d["scoped_ids"] == {"plan_id": "p1"}

    def test_empty_optional_fields(self):
        state = build_runtime_state(
            session_id="s1",
            user_id="u1",
            session_type="learning",
            current_stage="intro",
            user_text="hi",
        )
        assert state.context_summary == ""
        assert state.scoped_ids == {}
        assert state.session_facts == {}


class TestBuildGraphContext:
    def test_memory_snapshot_bounds_profile_summary(self):
        snapshot = build_graph_memory_snapshot(profile_summary="x" * (MAX_PROFILE_SUMMARY_LENGTH + 10))

        assert isinstance(snapshot, GraphMemorySnapshot)
        assert len(snapshot.profile_summary) == MAX_PROFILE_SUMMARY_LENGTH
        assert snapshot.available is True
        assert snapshot.source == "learner_profile"

    def test_memory_snapshot_redacts_sensitive_marker(self):
        snapshot = build_graph_memory_snapshot(profile_summary="provider payload included api key")

        assert "REDACTED" in snapshot.profile_summary

    def test_rag_context_bounds_and_redacts_chunks(self):
        context = build_graph_rag_context(
            knowledge_point_id="kp1",
            query="why closure state matters",
            chunks=[
                {
                    "chunk_id": "chunk1",
                    "chunk_type": "outline",
                    "title": "Closure State",
                    "content": "x" * (MAX_RAG_CHUNK_CONTENT_LENGTH + 20),
                    "source_url": "https://docs.example/closure",
                    "relevance_rank": "0.5",
                },
                {
                    "chunk_id": "chunk2",
                    "chunk_type": "example",
                    "title": "Unsafe",
                    "content": "solution_reference should not leak",
                },
            ],
        )

        assert isinstance(context, GraphRagContext)
        assert context.knowledge_point_id == "kp1"
        assert context.retrieval_status == "available"
        assert context.source_scope == "knowledge_point"
        assert len(context.chunks[0].content) == MAX_RAG_CHUNK_CONTENT_LENGTH
        assert "REDACTED" in context.chunks[1].content
        assert context.chunks[0].relevance_rank == 0.5

    def test_rag_context_caps_chunk_count_and_serializes(self):
        context = build_graph_rag_context(
            knowledge_point_id="kp1",
            query="",
            chunks=[
                {"chunk_id": f"chunk{i}", "chunk_type": "outline", "title": "T", "content": "C"}
                for i in range(MAX_RAG_CHUNKS + 3)
            ],
            retrieval_status="fallback",
        )

        serialized = context.to_dict()
        assert len(context.chunks) == MAX_RAG_CHUNKS
        assert serialized["retrieval_status"] == "fallback"
        assert len(serialized["chunks"]) == MAX_RAG_CHUNKS

    def test_human_checkpoint_bounds_and_redacts(self):
        checkpoint = build_graph_human_checkpoint(
            checkpoint_id="cp1",
            checkpoint_type="safety",
            reason="direct_answer_request",
            prompt="x" * (MAX_HUMAN_CHECKPOINT_PROMPT_LENGTH + 20),
            scope="teaching_safety",
            metadata={
                "current_stage": "concept_intro",
                "api_key": "sk-secret",
                "raw_prompt": "system prompt content",
            },
        )

        assert isinstance(checkpoint, GraphHumanCheckpoint)
        assert checkpoint.checkpoint_id == "cp1"
        assert checkpoint.checkpoint_type == "safety"
        assert len(checkpoint.prompt) == MAX_HUMAN_CHECKPOINT_PROMPT_LENGTH
        assert checkpoint.metadata["current_stage"] == "concept_intro"
        assert checkpoint.metadata["api_key"] == "[REDACTED]"
        assert checkpoint.metadata["raw_prompt"] == "[REDACTED]"

    def test_human_checkpoint_serializes(self):
        checkpoint = build_graph_human_checkpoint(
            checkpoint_id="cp2",
            checkpoint_type="clarification",
            reason="feynman_readiness_unclear",
            prompt="请再具体说明原因。",
            metadata={"solution_reference": "do not leak"},
        )

        serialized = checkpoint.to_dict()
        assert serialized["checkpoint_id"] == "cp2"
        assert serialized["checkpoint_type"] == "clarification"
        assert serialized["metadata"]["solution_reference"] == "[REDACTED]"


class TestBuildCheckpointThreadState:
    def test_builds_deterministic_thread_config(self):
        state = build_checkpoint_thread_state(
            session_id="s1",
            user_id="u1",
            session_type="learning",
            checkpoint_ns="learning",
        )
        assert state.thread_id == "aearn:learning:s1"
        assert state.checkpoint_ns == "learning"
        assert state.metadata["session_id"] == "s1"
        assert state.metadata["durable_state_owner"] == "service"
        assert state.to_config()["configurable"] == {
            "thread_id": "aearn:learning:s1",
            "checkpoint_ns": "learning",
        }

    def test_thread_id_includes_session_type(self):
        learning = build_checkpoint_thread_state(
            session_id="same-session",
            user_id="u1",
            session_type="learning",
        )
        review = build_checkpoint_thread_state(
            session_id="same-session",
            user_id="u1",
            session_type="review",
        )
        assert learning.thread_id != review.thread_id

    def test_includes_optional_checkpoint_id(self):
        state = build_checkpoint_thread_state(
            session_id="s1",
            user_id="u1",
            session_type="learning",
            checkpoint_id="cp1",
        )
        assert state.checkpoint_id == "cp1"
        assert state.to_config()["configurable"]["checkpoint_id"] == "cp1"

    def test_redacts_metadata(self):
        state = build_checkpoint_thread_state(
            session_id="s1",
            user_id="u1",
            session_type="learning",
            metadata={
                "reason": "safe",
                "api_key": "sk-secret",
                "raw_prompt": "system prompt content",
            },
        )
        assert state.metadata["reason"] == "safe"
        assert state.metadata["api_key"] == "[REDACTED]"
        assert state.metadata["raw_prompt"] == "[REDACTED]"

    def test_bounds_long_thread_id_with_hash_suffix(self):
        state = build_checkpoint_thread_state(
            session_id="s" * 400,
            user_id="u1",
            session_type="learning",
        )
        assert len(state.thread_id) <= MAX_THREAD_ID_LENGTH
        assert state.thread_id.startswith("aearn:learning")


class TestMakeIntent:
    def test_basic_intent(self):
        intent = make_intent(
            IntentType.STAGE_UPDATE,
            "learning_session",
            {"new_stage": "practice_support"},
        )
        assert isinstance(intent, GraphIntent)
        assert intent.intent_type == IntentType.STAGE_UPDATE
        assert intent.target == "learning_session"
        assert intent.payload["new_stage"] == "practice_support"

    def test_redacts_sensitive_payload(self):
        intent = make_intent(
            IntentType.PERSISTENCE,
            "session_store",
            {"data": "ok", "api_key": "sk-secret-123"},
        )
        assert intent.payload["data"] == "ok"
        assert intent.payload["api_key"] == "[REDACTED]"

    def test_to_dict(self):
        intent = make_intent(IntentType.TOOL_CALL, "run_code", {"code": "print(1)"})
        d = intent.to_dict()
        assert d["intent_type"] == "tool_call"
        assert d["target"] == "run_code"
        assert d["payload"]["code"] == "print(1)"


class TestValidateIntents:
    def test_valid_intents(self):
        intents = [
            make_intent(IntentType.STAGE_UPDATE, "session", {"stage": "check"}),
            make_intent(IntentType.FEEDBACK_REQUEST, "user", {"question": "ok?"}),
        ]
        errors = validate_intents(intents)
        assert errors == []

    def test_too_many_intents(self):
        intents = [
            make_intent(IntentType.SIDE_EFFECT, f"target_{i}")
            for i in range(MAX_INTENTS_PER_RUN + 3)
        ]
        errors = validate_intents(intents)
        assert any("too many" in e for e in errors)

    def test_empty_target(self):
        intent = GraphIntent(intent_type=IntentType.PERSISTENCE, target="", payload={})
        errors = validate_intents([intent])
        assert any("empty target" in e for e in errors)


class TestGraphRuntimeBoundaryContract:
    def test_contract_documents_all_runtime_layers(self):
        contract = graph_runtime_boundary_contract()
        layers = {item.layer for item in contract.responsibilities}
        assert layers == {
            GraphRuntimeLayer.GRAPH,
            GraphRuntimeLayer.SERVICE,
            GraphRuntimeLayer.REPOSITORY,
            GraphRuntimeLayer.API,
            GraphRuntimeLayer.SSE,
        }
        graph = next(item for item in contract.responsibilities if item.layer == GraphRuntimeLayer.GRAPH)
        service = next(item for item in contract.responsibilities if item.layer == GraphRuntimeLayer.SERVICE)
        assert "typed_intent_production" in graph.owns
        assert "repository_writes" in graph.does_not_own
        assert "intent_execution" in service.owns

    def test_contract_documents_intent_consumption_owner(self):
        rule = boundary_rule_for_intent_type(IntentType.PERSISTENCE)
        assert rule is not None
        assert rule.produced_by == GraphRuntimeLayer.GRAPH
        assert rule.consumed_by == GraphRuntimeLayer.SERVICE
        assert rule.durable_write_request is True

    def test_contract_serializes_without_enums(self):
        d = graph_runtime_boundary_contract().to_dict()
        assert d["responsibilities"][0]["layer"] == "graph"
        assert any(item["intent_type"] == "tool_call" for item in d["intent_rules"])

    def test_boundary_validation_accepts_scoped_learning_intents(self):
        errors = validate_boundary_intents(
            [make_intent(IntentType.STAGE_UPDATE, "learning_session")],
            allowed_intent_targets={IntentType.STAGE_UPDATE: ("learning_session",)},
        )
        assert errors == []

    def test_boundary_validation_rejects_unscoped_intent_type(self):
        errors = validate_boundary_intents(
            [make_intent(IntentType.PERSISTENCE, "learning_session")],
            allowed_intent_targets={IntentType.STAGE_UPDATE: ("learning_session",)},
        )
        assert any("type persistence is not allowed" in error for error in errors)

    def test_boundary_validation_rejects_unknown_target_for_scope(self):
        errors = validate_run_result_for_boundary(
            build_run_result(
                next_stage="practice_support",
                intents=[make_intent(IntentType.STAGE_UPDATE, "attempts")],
            ),
            allowed_intent_targets={IntentType.STAGE_UPDATE: ("learning_session",)},
        )
        assert any("target 'attempts' is not allowed" in error for error in errors)


class TestBuildRunResult:
    def test_basic_result(self):
        intent = make_intent(IntentType.STAGE_UPDATE, "session", {"stage": "check"})
        result = build_run_result(
            next_stage="concept_check",
            intents=[intent],
            diagnostics="user answered correctly",
        )
        assert isinstance(result, GraphRunResult)
        assert result.next_stage == "concept_check"
        assert len(result.intents) == 1
        assert result.diagnostics == "user answered correctly"

    def test_caps_intents(self):
        intents = [
            make_intent(IntentType.SIDE_EFFECT, f"t{i}")
            for i in range(MAX_INTENTS_PER_RUN + 5)
        ]
        result = build_run_result(next_stage="done", intents=intents)
        assert len(result.intents) == MAX_INTENTS_PER_RUN

    def test_validate_valid_result(self):
        result = build_run_result(
            next_stage="practice_support",
            intents=[make_intent(IntentType.PERSISTENCE, "db")],
        )
        errors = validate_run_result(result)
        assert errors == []

    def test_validate_empty_next_stage(self):
        result = GraphRunResult(next_stage="", intents=(), diagnostics="")
        errors = validate_run_result(result)
        assert any("empty next_stage" in e for e in errors)

    def test_to_dict(self):
        result = build_run_result(
            next_stage="done",
            intents=[make_intent(IntentType.TOOL_CALL, "run")],
            safe_context={"node": "final"},
        )
        d = result.to_dict()
        assert d["next_stage"] == "done"
        assert len(d["intents"]) == 1
        assert d["safe_context"]["node"] == "final"


class TestBuildFallback:
    def test_basic_fallback(self):
        fb = build_fallback(
            reason="model timeout",
            fallback_stage="concept_intro",
            safe_message="服务暂时不可用，请稍后重试。",
        )
        assert isinstance(fb, GraphFallback)
        assert fb.reason == "model timeout"
        assert fb.fallback_stage == "concept_intro"
        assert fb.recoverable is True

    def test_redacts_stack_trace_in_reason(self):
        fb = build_fallback(
            reason="Traceback (most recent call last): File ...",
            fallback_stage="intro",
        )
        assert "internal error" in fb.reason
        assert "Traceback" not in fb.reason

    def test_redacts_api_key_in_reason(self):
        fb = build_fallback(
            reason="Failed with api_key=sk-abc123",
            fallback_stage="intro",
        )
        assert "internal error" in fb.reason
        assert "sk-abc123" not in fb.reason

    def test_non_recoverable(self):
        fb = build_fallback(
            reason="invalid session",
            fallback_stage="error",
            recoverable=False,
        )
        assert fb.recoverable is False

    def test_to_dict(self):
        fb = build_fallback(reason="timeout", fallback_stage="intro", safe_message="retry")
        d = fb.to_dict()
        assert d["reason"] == "timeout"
        assert d["fallback_stage"] == "intro"
        assert d["safe_message"] == "retry"
        assert d["recoverable"] is True


class TestRedaction:
    def test_redacts_mapping_sensitive_keys(self):
        data = {
            "title": "hello",
            "solution_reference": "secret answer",
            "raw_prompt": "system prompt content",
        }
        result = redact_value(data)
        assert result["title"] == "hello"
        assert result["solution_reference"] == "[REDACTED]"
        assert result["raw_prompt"] == "[REDACTED]"

    def test_redacts_nested_mapping(self):
        data = {
            "outer": {
                "api_key": "sk-123",
                "safe": "ok",
            }
        }
        result = redact_value(data)
        assert result["outer"]["api_key"] == "[REDACTED]"
        assert result["outer"]["safe"] == "ok"

    def test_redacts_long_string_with_marker(self):
        long_content = "x" * 100 + "solution_reference" + "y" * 150
        result = redact_value(long_content)
        assert "REDACTED" in result

    def test_short_string_with_marker_is_redacted(self):
        short = "solution_reference"
        result = redact_value(short)
        assert "REDACTED" in result

    def test_string_redaction_catches_spaced_sensitive_markers(self):
        assert "REDACTED" in redact_value("hidden tests include private cases")
        assert "REDACTED" in redact_value("raw prompt: internal instructions")
        assert "REDACTED" in redact_value("provider error included api key sk-test")

    def test_list_redaction(self):
        data = [{"api_key": "secret"}, "normal", {"safe": True}]
        result = redact_value(data)
        assert result[0]["api_key"] == "[REDACTED]"
        assert result[1] == "normal"
        assert result[2]["safe"] is True

    def test_caps_list_length(self):
        data = list(range(30))
        result = redact_value(data)
        assert len(result) == 20

    def test_primitives_pass_through(self):
        assert redact_value(42) == 42
        assert redact_value(3.14) == 3.14
        assert redact_value(True) is True
        assert redact_value(None) is None
