"""Tests for onboarding graph orchestration."""
from __future__ import annotations

from app.agents.graphs.onboarding_graph import (
    invoke_onboarding_orchestration,
    onboarding_error_to_fallback,
    onboarding_result_to_run_result,
)
from app.agents.onboarding.onboarding_slot_extractor import ExtractedSlots
from app.services.conversations.onboarding_conversation import normalize_onboarding_agent_message


def _missing_language_slots(question: str = "你想主学哪门语言？") -> ExtractedSlots:
    return ExtractedSlots(
        missing_slot_question=question,
        plan_ready=False,
        slot_statuses={
            "language": {
                "status": "missing",
                "clarification_question": question,
            },
        },
    )


class TestOnboardingOrchestration:
    def _base_input(self, **overrides):
        defaults = {
            "conversation_id": "conv1",
            "user_id": "u1",
            "status": "active",
            "user_text": "我想学 Python",
            "plan_ready": False,
            "has_stashed_draft": False,
            "revising": False,
            "language": None,
            "target_level": None,
            "goal_text": None,
            "missing_slot_question": "你想主学哪门语言？",
            "core_slots_changed": False,
        }
        defaults.update(overrides)
        return defaults

    def test_clarify_when_not_ready(self):
        result = invoke_onboarding_orchestration(**self._base_input(
            plan_ready=False,
        ))
        assert result["next_action"] == "clarify"
        assert result["intent_type"] == "feedback_request"

    def test_generate_route_when_ready(self):
        result = invoke_onboarding_orchestration(**self._base_input(
            plan_ready=True,
            language="python",
            target_level="beginner",
            goal_text="做数据分析",
        ))
        assert result["next_action"] == "generate_route"
        assert result["intent_type"] == "tool_call"
        assert result["intent_payload"]["tool"] == "build_plan_draft"

    def test_await_confirm_when_draft_exists(self):
        result = invoke_onboarding_orchestration(**self._base_input(
            plan_ready=True,
            has_stashed_draft=True,
            language="python",
            target_level="beginner",
            goal_text="做数据分析",
            user_text="看起来不错",
        ))
        assert result["next_action"] == "await_confirm"

    def test_confirm_when_user_confirms_stashed_draft(self):
        result = invoke_onboarding_orchestration(**self._base_input(
            plan_ready=True,
            has_stashed_draft=True,
            language="python",
            target_level="beginner",
            goal_text="做数据分析",
            user_text="确认，开始学习",
        ))
        assert result["next_action"] == "confirm_plan"
        assert result["intent_type"] == "persistence"
        assert result["intent_payload"]["target"] == "confirm_plan"

    def test_revise_when_user_says_change(self):
        result = invoke_onboarding_orchestration(**self._base_input(
            plan_ready=True,
            has_stashed_draft=True,
            language="python",
            target_level="beginner",
            goal_text="做数据分析",
            user_text="我想改成 JavaScript",
        ))
        assert result["next_action"] == "revise_route"
        assert result["intent_type"] == "tool_call"

    def test_revise_when_core_slots_changed(self):
        result = invoke_onboarding_orchestration(**self._base_input(
            plan_ready=True,
            has_stashed_draft=True,
            revising=False,
            core_slots_changed=True,
            language="javascript",
            target_level="beginner",
            goal_text="做网站",
            user_text="好的",
        ))
        assert result["next_action"] == "revise_route"

    def test_revise_when_revising_flag(self):
        result = invoke_onboarding_orchestration(**self._base_input(
            plan_ready=True,
            has_stashed_draft=True,
            revising=True,
            language="python",
            target_level="intermediate",
            goal_text="做自动化",
            user_text="好",
        ))
        assert result["next_action"] == "revise_route"

    def test_clarify_question_passed_through(self):
        result = invoke_onboarding_orchestration(**self._base_input(
            plan_ready=False,
            missing_slot_question="你现在大概是什么水平？",
        ))
        assert result["intent_payload"]["question"] == "你现在大概是什么水平？"

    def test_continue_chat_fallback(self):
        result = invoke_onboarding_orchestration(**self._base_input(
            plan_ready=True,
            language="python",
            target_level=None,
            goal_text=None,
        ))
        assert result["next_action"] == "continue_chat"


class TestOnboardingContractAdapters:
    def test_run_result_from_tool_call(self):
        result = {
            "next_action": "generate_route",
            "intent_type": "tool_call",
            "intent_payload": {"tool": "build_plan_draft", "language": "python"},
        }
        run_result = onboarding_result_to_run_result(result)
        assert run_result.next_stage == "generate_route"
        assert len(run_result.intents) == 1
        assert run_result.intents[0].intent_type.value == "tool_call"

    def test_run_result_from_feedback(self):
        result = {
            "next_action": "clarify",
            "intent_type": "feedback_request",
            "intent_payload": {"question": "你想学什么？"},
        }
        run_result = onboarding_result_to_run_result(result)
        assert run_result.next_stage == "clarify"
        assert len(run_result.intents) == 1
        assert run_result.intents[0].intent_type.value == "feedback_request"

    def test_run_result_from_persistence(self):
        result = {
            "next_action": "confirm_plan",
            "intent_type": "persistence",
            "intent_payload": {"target": "confirm_plan", "conversation_id": "conv1"},
        }
        run_result = onboarding_result_to_run_result(result)
        assert run_result.next_stage == "confirm_plan"
        assert len(run_result.intents) == 1
        assert run_result.intents[0].intent_type.value == "persistence"

    def test_run_result_from_no_intent(self):
        result = {
            "next_action": "continue_chat",
            "intent_type": "none",
            "intent_payload": {},
        }
        run_result = onboarding_result_to_run_result(result)
        assert run_result.next_stage == "continue_chat"
        assert len(run_result.intents) == 0

    def test_fallback_redacts_error(self):
        fb = onboarding_error_to_fallback(
            RuntimeError("Traceback: secret api_key leaked"),
            fallback_action="continue_chat",
        )
        assert "internal error" in fb.reason
        assert "api_key" not in fb.reason
        assert fb.recoverable is True


class TestOnboardingChatFirstMessageNormalization:
    def test_preserves_advisory_answer_before_missing_slot_followup(self):
        answer = (
            "做 AI Agent 通常优先用 Python，因为工具调用、自动化和后端生态更成熟。"
            "如果偏网页产品，再考虑 JavaScript/TypeScript。"
        )

        result = normalize_onboarding_agent_message(
            answer,
            slots=_missing_language_slots(),
            route_ready=False,
        )

        assert result.startswith(answer)
        assert "你想主学哪门语言" in result
        assert result != "你想主学哪门语言？"

    def test_preserves_capability_answer_without_turning_it_into_a_form_prompt(self):
        answer = "Aearn 可以先帮你选学习方向，再把目标拆成路线、练习和复习节奏。"

        result = normalize_onboarding_agent_message(
            answer,
            slots=_missing_language_slots("你更想先学哪类编程方向？"),
            route_ready=False,
        )

        assert result.startswith(answer)
        assert "你更想先学哪类编程方向" in result

    def test_preserves_comparison_answer_before_missing_slot_followup(self):
        answer = (
            "如果目标是先做可运行的工具型 Agent，我建议先选 Python；"
            "如果更偏网页产品和界面交互，JavaScript 会更贴近。"
        )

        result = normalize_onboarding_agent_message(
            answer,
            slots=_missing_language_slots(),
            route_ready=False,
        )

        assert result.startswith(answer)
        assert "你想主学哪门语言" in result

    def test_does_not_duplicate_followup_when_answer_already_contains_question(self):
        answer = "Python 适合先做工具型 Agent。你想主学哪门语言？"

        result = normalize_onboarding_agent_message(
            answer,
            slots=_missing_language_slots(),
            route_ready=False,
        )

        assert result == answer

    def test_does_not_duplicate_semantic_language_followup(self):
        answer = (
            "做 AI Agent 通常优先用 Python，因为工具调用和自动化生态更成熟。"
            "你想用哪种编程语言来实现 agent 呢？我们目前支持 JavaScript、Python、Java、C++和HTML/CSS。"
        )

        result = normalize_onboarding_agent_message(
            answer,
            slots=_missing_language_slots(),
            route_ready=False,
        )

        assert result == answer
        assert "你想主学哪门语言" not in result

    def test_still_blocks_route_ready_claim_when_required_slot_is_missing(self):
        result = normalize_onboarding_agent_message(
            "信息够了，我生成一份路线卡片。",
            slots=_missing_language_slots(),
            route_ready=False,
        )

        assert "信息够" not in result
        assert "路线卡" not in result
        assert "你想主学哪门语言" in result

    def test_empty_model_text_stays_empty_so_route_can_return_model_unavailable(self):
        result = normalize_onboarding_agent_message(
            "   ",
            slots=_missing_language_slots(),
            route_ready=False,
        )

        assert result == ""
