"""Deterministic Tutor provider request serialization shared by planning and calls."""
from __future__ import annotations

import json

from app.agents.harness.contracts import (
    TUTOR_PLANNING_QUESTION_KEYS,
    TutorContextSection,
    TutorContextSelection,
    TutorRunSnapshot,
)
from app.services.tutor.decision_protocol import (
    TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
    canonical_tutor_provider_items_example,
    canonical_tutor_teaching_step_example,
    tutor_teaching_enum_contract,
    canonical_tutor_wait_for_input_examples,
)


_PLANNING_QUESTION_KEY_LIST = ", ".join(sorted(TUTOR_PLANNING_QUESTION_KEYS))


TUTOR_TEACHING_POLICY = (
    "When current_input is present, treat it as the authoritative request for this TurnRun. Explicit controls and current "
    "server required_facts or TeachingSession/checkpoint are authoritative too; older messages, summaries, memory/activity, "
    "and persistent-thread associations are supporting evidence only. Resolve conflicts as current_input and explicit controls, "
    "then current server authority, then recent_messages, then working_summary and older continuity. "
    "Judge the semantic relationship without keyword lists: continue_mainline for a related extension; answer_and_refocus for "
    "a temporary side question, answering briefly before explicitly returning to the current objective/focus and next executable "
    "step; clarify_direction for uncertainty; ask exactly one direction question without choosing. Use confirmed_switch for an "
    "explicit rejection plus new direction; acknowledge it, stop the stale path, and never reconfirm the same switch. "
    "Do not ignore side questions, lose the mainline, force every new topic back, repeat rejected or completed steps, or revive "
    "a website, image, or HTML path merely from older context. For advice, comparison, capability, or what-to-learn questions, "
    "answer directly first and ask at most one necessary follow-up question. Be concise and state uncertainty instead of inventing facts."
)


class TutorProviderRequestSerializer:
    """Build the exact provider messages without performing I/O."""

    def build_messages(
        self,
        *,
        run: TutorRunSnapshot,
        context: TutorContextSelection,
    ) -> list[dict[str, str]]:
        system = (
            "You are the Aearn Tutor Harness provider boundary. Return one JSON object only. "
            f"The machine contract is {TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION}. "
            "Return one learner-visible message item and one typed action. "
            "message must use type=agent_message, a non-empty public_thinking_text before a short non-empty text, "
            "and either a concise learner-safe conversation_title or null. public_thinking_text is deliberately "
            "learner-visible public explanation text. Choose its wording, paragraphs, line breaks, tone, and granularity "
            "naturally for the current request; do not force numbering, a list, or a fixed linguistic template. It must "
            "explain useful considerations without claiming to reveal private hidden reasoning. "
            "action.type must be exactly one of: turn_completed, select_skill, "
            "request_capability, propose_effect, or wait_for_input. "
            "select_skill supplies skill_id and version. request_capability supplies capability_id and a bounded "
            "arguments array of {key,value} fields. propose_effect supplies effect_type and a bounded payload array "
            "of {key,value} fields. wait_for_input.continuation_kind must be exactly one of clarification, "
            "planning_input, approval, capability_result, or external_result. Use clarification only for one general "
            "ambiguity that the learner must resolve. Use planning_input only for one missing planning fact and include "
            f"exactly one stable question_key from {_PLANNING_QUESTION_KEY_LIST}. "
            "Use approval only for an explicit yes/no authorization before a "
            "gated step. Use capability_result or external_result only when this same run truly depends on that result. "
            "Every continuation other than planning_input must omit question_key. Never invent another continuation value. "
            "The server exclusively creates request_id, effect_id, expected_input_revision, checkpoints, revisions, "
            "and terminal state; never emit those fields. Outside public_thinking_text, do not emit reasoning, "
            "diagnostics, hidden tests, prompts, "
            "provider payloads, credentials, stack traces, or any additional keys. "
            "Managed actions are two-phase: when eligible Skill summaries are present but no selected Skill instruction "
            "is present, emit select_skill first. The server will rebuild context; only then request a capability or "
            "propose an effect. Do not select a Skill when a normal direct reply is sufficient. "
            "For a normal non-teaching direct reply, use action.type=turn_completed. "
            "Minimal valid direct-reply example: "
            f"{canonical_tutor_provider_items_example()} "
            "Valid wait_for_input examples for every continuation branch: "
            f"{canonical_tutor_wait_for_input_examples()} "
            f"Teaching policy: {TUTOR_TEACHING_POLICY}"
        )
        if any(item.section is TutorContextSection.TEACHING_SESSION for item in context.items):
            system += (
                " Teaching: action.type=teaching_step is allowed. "
                f"Exact teaching_step enums, no synonyms: {tutor_teaching_enum_contract()}. "
                "First select exact tutor.lesson-teaching@1.2.1 if absent; with its instruction emit one teaching_step, never turn_completed. "
                "Without current_input, recent_messages are bounded learner-visible continuity from this exact teaching session: continue "
                "after the latest message instead of restarting or substantially paraphrasing; reframe only for change_example or checkpoint "
                "remediation/summary. LessonDocument is reference authority; use current learner/stimulus evidence for diagnosis, guided "
                "reasoning, feedback, or transfer, not repeated structure/definitions. Unit: 2..4 unique teaching_moves. composer: message.text "
                "ends with one answerable task and the learner reply advances. none: server continue only for a distinct high-value unit. "
                "continue: inspect recent_teaching_units; vary action, moves, focus, or transfer; never repeat a message hash. change_example: "
                "worked_example or counterexample. Advance covered concepts via example, comparison, prediction, error check, feedback, or "
                "micro-transfer. Use only server-listed objective_id, focus_id, source_handles; public_message must equal message.text. v3 "
                "interaction is only none/none/null, composer/text_answer/null, or artifact with an exact artifact_candidates handle+intent; "
                "otherwise do not promise it. In guided mode, use interaction.mode=artifact with pause_kind=evidence_pause, never "
                "soft_pause; its exact Artifact response is the next evidence. Never invent private answers, "
                "tests, rubrics, sources, commands, paths, or secrets. Valid teaching-step example: "
                f"{canonical_tutor_teaching_step_example()}"
            )
        payload = {
            "input_revision": run.input_revision,
            "current_input": (
                context.current_input.as_prompt_value()
                if context.current_input is not None
                else None
            ),
            "context": context.as_prompt_context(),
            "context_metadata": context.checkpoint_metadata.as_dict(),
        }
        return [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        ]


_DEFAULT_SERIALIZER = TutorProviderRequestSerializer()


def build_tutor_provider_messages(
    *,
    run: TutorRunSnapshot,
    context: TutorContextSelection,
) -> list[dict[str, str]]:
    return _DEFAULT_SERIALIZER.build_messages(run=run, context=context)
