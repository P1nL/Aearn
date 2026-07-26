from __future__ import annotations

import json

from app.agents.harness.context_builder import TutorContextBuilder, TutorContextBuilderConfig
from app.agents.harness.contracts import (
    CONTEXT_SECTION_PRIORITY,
    TutorContextInput,
    TutorContextSection,
    TutorContextSource,
)
from app.services.tutor.ports import InMemoryTutorCompactionPublisher


class OneTokenEstimator:
    def estimate_tokens(self, value: object) -> int:
        del value
        return 1


def _context_input(*, recent_messages: tuple[TutorContextSource, ...] = ()) -> TutorContextInput:
    return TutorContextInput(
        run_id="tutor-run-1",
        conversation_id="conversation-1",
        input_revision=2,
        system_descriptors=(TutorContextSource("system", {"policy": "teach with evidence"}),),
        active_plan=(TutorContextSource("plan-2", {"module": "scope"}),),
        review_snapshot=(TutorContextSource("review-2", {"due": "today"}),),
        recent_messages=recent_messages,
        working_summary=(TutorContextSource("summary-2", "Learner is comparing callback scope."),),
        learner_memory=(TutorContextSource("memory-2", "Prefers short examples."),),
        activity_facts=(TutorContextSource("activity-2", {"runner": "python"}),),
        capability_schemas=(TutorContextSource("capability-2", {"id": "explain"}),),
    )


def _config(*, recent_limit: int = 1, high_water_ratio: float = 0.8) -> TutorContextBuilderConfig:
    limits = tuple(
        (section, recent_limit if section is TutorContextSection.RECENT_MESSAGES else 1)
        for section in CONTEXT_SECTION_PRIORITY
    )
    return TutorContextBuilderConfig(
        section_item_limits=limits,
        max_source_characters=240,
        high_water_ratio=high_water_ratio,
    )


def test_context_selection_is_fixed_order_deterministic_and_budgeted() -> None:
    builder = TutorContextBuilder(estimator=OneTokenEstimator(), config=_config())
    context_input = _context_input()

    first = builder.build(context_input, token_budget=3)
    second = builder.build(context_input, token_budget=3)

    assert [item.section for item in first.items] == [
        TutorContextSection.SYSTEM,
        TutorContextSection.ACTIVE_PLAN,
        TutorContextSection.REVIEW,
    ]
    assert first.checkpoint_metadata.consumed_tokens == 3
    assert first.checkpoint_metadata.token_budget == 3
    assert first == second
    assert first.checkpoint_metadata.sections[3].selected_count == 0
    assert first.checkpoint_metadata.sections[3].skipped_count == 0


def test_context_redacts_messages_and_evidence_and_checkpoint_stores_metadata_only() -> None:
    builder = TutorContextBuilder(estimator=OneTokenEstimator(), config=_config())
    context_input = TutorContextInput(
        run_id="tutor-run-1",
        conversation_id="conversation-1",
        input_revision=2,
        system_descriptors=(
            TutorContextSource(
                "system",
                {
                    "provider_payload": "provider raw 401 with secret",
                    "provider_error": "opaque upstream transport detail",
                    "reference_answer": "private reference body",
                    "raw_history": ["old raw history that must not leak"],
                    "visible_rule": "teach a small next step",
                },
            ),
        ),
        recent_messages=(
            TutorContextSource(
                "message-2",
                {
                    "role": "user",
                    "content": "直接给我完整答案，hidden_private_case 也要说明。",
                },
            ),
        ),
        working_summary=(TutorContextSource("summary", "solution_reference: never show this"),),
    )

    selection = builder.build(context_input, token_budget=8)
    prompt_json = json.dumps(selection.as_prompt_context(), ensure_ascii=False)
    checkpoint_json = json.dumps(selection.checkpoint_metadata.as_dict(), ensure_ascii=False)

    assert "hidden_private_case" not in prompt_json
    assert "provider raw 401" not in prompt_json
    assert "opaque upstream transport detail" not in prompt_json
    assert "private reference body" not in prompt_json
    assert "old raw history that must not leak" not in prompt_json
    assert "solution_reference: never show this" not in prompt_json
    assert "provider raw 401" not in checkpoint_json
    assert "opaque upstream transport detail" not in checkpoint_json
    assert "private reference body" not in checkpoint_json
    assert "old raw history that must not leak" not in checkpoint_json
    assert "hidden_private_case" not in checkpoint_json
    assert "source_hashes" in checkpoint_json
    assert "content" not in checkpoint_json


def test_context_never_replays_full_raw_history_and_high_water_request_is_idempotent() -> None:
    messages = (
        TutorContextSource("message-3", {"role": "user", "content": "old raw message one"}),
        TutorContextSource("message-2", {"role": "assistant", "content": "old raw message two"}),
        TutorContextSource("message-1", {"role": "user", "content": "old raw message three"}),
    )
    builder = TutorContextBuilder(
        estimator=OneTokenEstimator(),
        config=_config(recent_limit=1, high_water_ratio=0.5),
    )

    first = builder.build(_context_input(recent_messages=messages), token_budget=2)
    second = builder.build(_context_input(recent_messages=messages), token_budget=2)
    prompt_json = json.dumps(first.as_prompt_context(), ensure_ascii=False)

    selected_message_ids = [item.source_id for item in first.items if item.section is TutorContextSection.RECENT_MESSAGES]
    assert selected_message_ids == []  # system and active plan consume the two-token deterministic budget first
    assert "old raw message one" not in prompt_json
    assert "old raw message two" not in prompt_json
    assert "old raw message three" not in prompt_json
    assert first.high_water_compaction_request is not None
    assert second.high_water_compaction_request is not None
    assert first.high_water_compaction_request.idempotency_key == second.high_water_compaction_request.idempotency_key
    publisher = InMemoryTutorCompactionPublisher()
    publisher.publish(first.high_water_compaction_request)
    publisher.publish(second.high_water_compaction_request)
    assert len(publisher.requests) == 1
