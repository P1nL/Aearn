"""Unit tests for agent write tools."""

from app.agents.tooling.tools import (
    AgentSideEffects,
    LearningToolContext,
    do_record_attempt,
    do_record_diagnosis,
    do_trigger_code_run,
    do_update_learning_stage,
    do_update_learner_profile,
)
from app.services.conversations.learning_conversation import serialize_agent_side_effects


def _make_context(**overrides) -> LearningToolContext:
    defaults = {
        "session_id": "sess-1",
        "exercise_id": "ex-1",
        "current_stage": "concept_intro",
        "exercise": {"id": "ex-1", "runtime_profile": {"language": "python"}},
        "run_code_fn": None,
    }
    defaults.update(overrides)
    return LearningToolContext(**defaults)


class TestUpdateLearningStage:
    def test_valid_transition_accumulates(self):
        effects = AgentSideEffects()
        ctx = _make_context(current_stage="concept_intro")
        result = do_update_learning_stage(effects, ctx, "concept_qna", "user asked a question")
        assert result["success"] is True
        assert result["previous_stage"] == "concept_intro"
        assert result["new_stage"] == "concept_qna"
        assert len(effects.stage_updates) == 1
        assert effects.final_stage("concept_intro") == "concept_qna"
        assert effects.typed_intents[0].intent_type.value == "stage_update"
        assert effects.typed_intents[0].target == "learning_session"

    def test_invalid_transition_returns_error(self):
        effects = AgentSideEffects()
        ctx = _make_context(current_stage="concept_intro")
        result = do_update_learning_stage(effects, ctx, "practice_support", "skip ahead")
        assert result["success"] is False
        assert "Cannot transition" in result["error"]
        assert "allowed_transitions" in result
        assert len(effects.stage_updates) == 0

    def test_chained_transitions(self):
        effects = AgentSideEffects()
        ctx = _make_context(current_stage="concept_intro")
        do_update_learning_stage(effects, ctx, "readiness_check", "step 1")
        result = do_update_learning_stage(effects, ctx, "practice_support", "step 2")
        assert result["success"] is True
        assert effects.final_stage("concept_intro") == "practice_support"

    def test_practice_support_is_terminal(self):
        effects = AgentSideEffects()
        ctx = _make_context(current_stage="practice_support")
        result = do_update_learning_stage(effects, ctx, "concept_intro", "go back")
        assert result["success"] is False


class TestRecordDiagnosis:
    def test_records_non_empty_fields(self):
        effects = AgentSideEffects()
        result = do_record_diagnosis(
            effects,
            stuck_point="recursion base case",
            misconceptions="confuses return with print",
        )
        assert result["recorded"] is True
        assert "stuck_point" in result["fields"]
        assert "misconceptions" in result["fields"]
        assert len(effects.diagnosis_updates) == 1

    def test_empty_fields_excluded(self):
        effects = AgentSideEffects()
        result = do_record_diagnosis(effects, stuck_point="loops")
        assert result["fields"] == ["stuck_point"]
        assert "misconceptions" not in effects.diagnosis_updates[0]


class TestTriggerCodeRun:
    def test_returns_runner_result(self):
        def fake_runner(exercise, code):
            return {
                "runtime_status": "success",
                "stdout": "hello",
                "stderr": "",
                "test_pass_rate": 1.0,
                "test_results": [{"name": "test_1", "passed": True}],
            }

        ctx = _make_context(run_code_fn=fake_runner)
        effects = AgentSideEffects()
        result = do_trigger_code_run(ctx, "print('hello')", side_effects=effects)
        assert result["success"] is True
        assert result["stdout"] == "hello"
        assert result["test_pass_rate"] == 1.0
        assert effects.typed_intents[0].intent_type.value == "tool_call"
        assert effects.typed_intents[0].target == "trigger_code_run"
        assert effects.typed_intents[0].payload["runtime_status"] == "success"

    def test_unavailable_when_no_runner(self):
        ctx = _make_context(run_code_fn=None)
        result = do_trigger_code_run(ctx, "print('hi')")
        assert result["success"] is False
        assert "not available" in result["error"]


class TestRecordAttempt:
    def test_valid_attempt(self):
        effects = AgentSideEffects()
        ctx = _make_context()
        result = do_record_attempt(effects, ctx, "x = 1", "run")
        assert result["success"] is True
        assert "attempt_id" in result
        assert len(effects.attempt_records) == 1
        assert effects.attempt_records[0]["action"] == "run"
        assert effects.typed_intents[0].intent_type.value == "persistence"
        assert effects.typed_intents[0].target == "attempt"
        assert effects.typed_intents[0].payload["code_length"] == 5
        assert "x = 1" not in str(effects.typed_intents[0].to_dict())

    def test_invalid_action(self):
        effects = AgentSideEffects()
        ctx = _make_context()
        result = do_record_attempt(effects, ctx, "x = 1", "delete")
        assert result["success"] is False


class TestAgentSideEffects:
    def test_empty_has_no_stage_change(self):
        effects = AgentSideEffects()
        assert effects.has_stage_change() is False
        assert effects.final_stage("concept_intro") == "concept_intro"

    def test_final_stage_returns_last(self):
        effects = AgentSideEffects()
        effects.stage_updates.append({"new_stage": "concept_qna"})
        effects.stage_updates.append({"new_stage": "readiness_check"})
        assert effects.final_stage("concept_intro") == "readiness_check"
        assert effects.has_stage_change() is True


class TestTypedToolIntents:
    def test_record_diagnosis_emits_side_effect_intent(self):
        effects = AgentSideEffects()
        do_record_diagnosis(effects, stuck_point="loops")
        assert effects.typed_intents[0].intent_type.value == "side_effect"
        assert effects.typed_intents[0].target == "diagnosis"

    def test_update_learner_profile_emits_profile_update_intent(self):
        effects = AgentSideEffects()
        ctx = _make_context()
        result = do_update_learner_profile(
            effects,
            ctx,
            observation_type="weak_point",
            content="closures",
            confidence="confirmed",
        )
        assert result["success"] is True
        assert effects.typed_intents[0].intent_type.value == "profile_update"
        assert effects.typed_intents[0].target == "learner_profile"

    def test_serialize_side_effects_includes_typed_intents(self):
        effects = AgentSideEffects()
        ctx = _make_context()
        do_record_attempt(effects, ctx, "print('secret stays out')", "run")

        metadata = serialize_agent_side_effects(effects, session_id="sess-1")

        assert metadata["typed_intents"][0]["intent_type"] == "persistence"
        assert metadata["typed_intents"][0]["target"] == "attempt"
        assert metadata["typed_intents"][0]["payload"]["code_length"] == 25
        assert "print('secret stays out')" not in str(metadata["typed_intents"])
