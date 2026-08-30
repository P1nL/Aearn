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
    canonical_tutor_wait_for_input_examples,
)


_PLANNING_QUESTION_KEY_LIST = ", ".join(sorted(TUTOR_PLANNING_QUESTION_KEYS))


TUTOR_TEACHING_POLICY = (
    "When current_input is present, treat it as the authoritative request for this TurnRun and answer or acknowledge it "
    "before advancing any earlier lesson, exercise, setup, or plan. Prior context is supporting evidence only. "
    "Treat required_facts as server-authoritative facts that outrank every optional continuity source. "
    "Resolve conflicts in this order: current_input, then recent_messages, then working_summary, then learner_memory/activity; "
    "a working summary must never overwrite a newer correction or completion. "
    "A learner correction, interruption, refusal, goal change, or statement that a step is already complete overrides stale "
    "assumptions: briefly acknowledge the change, stop the stale path, and do not repeat completed or rejected steps unless "
    "the learner explicitly asks. For advice, comparison, capability, or what-to-learn questions, answer directly first and "
    "ask at most one necessary follow-up question. Do not force an earlier website, image, or HTML path merely because it "
    "appears in context. Be concise and learner-facing, and state uncertainty instead of inventing facts."
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
                " This teaching request also permits action.type=teaching_step. "
                "First select exact tutor.lesson-teaching@1.1.0 if it is not selected; after its instruction is present, "
                "use exactly one teaching_step and never use turn_completed as a teaching shortcut. When current_input is "
                "absent, recent_messages are bounded learner-visible continuity from this exact teaching session: continue "
                "after the latest message instead of restarting or substantially paraphrasing an explanation already given. "
                "Repeat or reframe only when the stimulus explicitly requests change_example, or checkpoint authority requires "
                "remediation or summary. LessonDocument is the stable reference; Tutor must use current learner/stimulus evidence "
                "for diagnosis, guided reasoning, immediate feedback, or transfer instead of restating document structure or definitions. "
                "A teaching unit must combine 2..4 unique teaching_moves. learner_response_mode=composer means message.text ends with one "
                "specific answerable task and the next step comes from a learner message; learner_response_mode=none permits a conditional "
                "server-projected continue only when another non-repetitive high-value unit exists. For continue, inspect recent_teaching_units "
                "and change action, move combination, focus, or transfer target; never replay the same message hash. change_example may preserve "
                "the purpose but must use worked_example or counterexample. A covered concept should normally advance to an example, comparison, "
                "prediction, error check, feedback, or micro-transfer rather than receive the same introductory definition again. teaching_step may "
                "reference only objective_id, focus_id, and source_handles listed by the server, and its public_message "
                "must exactly equal message.text. Valid teaching-step example: "
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
