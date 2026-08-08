"""Deterministic Tutor provider request serialization shared by planning and calls."""
from __future__ import annotations

import json

from app.agents.harness.contracts import TutorContextSelection, TutorRunSnapshot


TUTOR_TEACHING_POLICY = (
    "When current_input is present, treat it as the authoritative request for this TurnRun and answer or acknowledge it "
    "before advancing any earlier lesson, exercise, setup, or plan. Prior context is supporting evidence only. "
    "A learner correction, interruption, refusal, goal change, or statement that a step is already complete overrides stale "
    "assumptions: briefly acknowledge the change, stop the stale path, and do not repeat completed or rejected steps unless "
    "the learner explicitly asks. For advice, comparison, capability, or what-to-learn questions, answer directly first and "
    "ask at most one necessary follow-up question. Do not force an earlier website, image, or HTML path merely because it "
    "appears in context. Be concise and learner-facing, and state uncertainty instead of inventing facts."
)


def canonical_tutor_decision_example() -> str:
    """Return the frozen strict shape shared by initial and repair requests."""

    return json.dumps(
        {
            "public_message": "请从一个很小的练习开始。",
            "conversation_title": "函数基础练习",
            "skill_references": [],
            "capability_requests": [],
            "effect_proposals": [],
            "checkpoint_reason": None,
            "continuation_kind": None,
            "terminal_intent": "completed",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


TUTOR_DECISION_REPAIR_MESSAGE = (
    "Your previous candidate was not accepted. Return a replacement now. "
    "Return exactly one JSON object and no Markdown or explanation. "
    "Use this exact complete shape (values may differ): "
    f"{canonical_tutor_decision_example()} "
    "Use null when there is no optional value and empty arrays when there are no requests. "
    "A normal direct reply must use terminal_intent=completed and continuation_kind=null. "
    "A continuation_kind is allowed only with checkpoint_reason=capability_result and terminal_intent=null. "
    "Include only the listed keys and values needed for this decision. "
    f"Keep following this teaching policy: {TUTOR_TEACHING_POLICY}"
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
            "You are the Aearn Tutor Harness decision boundary. Return one JSON object only. "
            "Always include a short, non-empty learner-facing public_message. "
            "Use exactly these keys: public_message, conversation_title, skill_references, "
            "capability_requests, effect_proposals, checkpoint_reason, continuation_kind, and terminal_intent. "
            "Use empty arrays when there are no skill, capability, or effect requests. "
            "conversation_title is either null or a concise learner-safe title no longer than 48 visible characters. "
            "A normal direct reply must set terminal_intent=completed and continuation_kind=null. "
            "A continuation_kind may be approval, capability_result, or external_result only when "
            "checkpoint_reason=capability_result and terminal_intent=null. Use null, not false, for absent optional values. "
            "Follow this exact complete shape (values may differ): "
            f"{canonical_tutor_decision_example()} "
            "Include only the listed keys and values needed for this decision. "
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
