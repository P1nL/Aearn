"""Deterministic Tutor provider request serialization shared by planning and calls."""
from __future__ import annotations

import json

from app.agents.harness.contracts import TutorContextSelection, TutorRunSnapshot
from app.services.tutor.decision_protocol import (
    TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
    canonical_tutor_provider_items_example,
)


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
            "message must use type=agent_message, a short non-empty text, one to four public_thinking_steps, "
            "and either a concise learner-safe conversation_title or null. public_thinking_steps are deliberately "
            "learner-visible public explanations. Choose their wording, tone, ordering, and granularity naturally for "
            "the current request; do not force a fixed linguistic template or transition sequence. They must explain "
            "useful considerations without claiming to reveal private hidden reasoning. "
            "action.type must be exactly one of: turn_completed, select_skill, "
            "request_capability, propose_effect, or wait_for_input. "
            "select_skill supplies skill_id and version. request_capability supplies capability_id and a bounded "
            "arguments array of {key,value} fields. propose_effect supplies effect_type and a bounded payload array "
            "of {key,value} fields. wait_for_input supplies continuation_kind and, for plan-drafting questions, "
            "a stable question_key from language_id, goal_text, target_level, weekly_minutes, experience_level, "
            "teaching_preferences, or pace_constraints. "
            "The server exclusively creates request_id, effect_id, expected_input_revision, checkpoints, revisions, "
            "and terminal state; never emit those fields. Outside public_thinking_steps, do not emit reasoning, "
            "diagnostics, hidden tests, prompts, "
            "provider payloads, credentials, stack traces, or any additional keys. "
            "Managed actions are two-phase: when eligible Skill summaries are present but no selected Skill instruction "
            "is present, emit select_skill first. The server will rebuild context; only then request a capability or "
            "propose an effect. Do not select a Skill when a normal direct reply is sufficient. "
            "For a normal direct reply, use action.type=turn_completed. "
            "Minimal valid direct-reply example: "
            f"{canonical_tutor_provider_items_example()} "
            f"Teaching policy: {TUTOR_TEACHING_POLICY}"
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
