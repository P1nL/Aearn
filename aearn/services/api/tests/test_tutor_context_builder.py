from __future__ import annotations

import json

import pytest

from app.agents.harness.context_builder import TutorContextBuilder, TutorContextBuilderConfig
from app.agents.harness.contracts import (
    CONTEXT_SECTION_PRIORITY,
    TutorContextError,
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
        current_input=TutorContextSource("message-current", "我应该学哪些语言"),
        current_input_required=True,
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




def _section_metadata(selection: object, section: TutorContextSection):
    metadata = getattr(selection, "checkpoint_metadata")
    return next(item for item in metadata.sections if item.section is section)


def test_context_selection_is_fixed_order_deterministic_and_budgeted() -> None:
    builder = TutorContextBuilder(estimator=OneTokenEstimator(), config=_config())
    context_input = _context_input()

    first = builder.build(context_input, token_budget=3)
    second = builder.build(context_input, token_budget=3)

    assert first.current_input is not None
    assert first.current_input.content == "我应该学哪些语言"
    assert [item.section for item in first.items] == [
        TutorContextSection.SYSTEM,
        TutorContextSection.ACTIVE_PLAN,
    ]
    assert first.checkpoint_metadata.consumed_tokens == 3
    assert first.checkpoint_metadata.token_budget == 3
    assert first == second
    assert first.checkpoint_metadata.current_input is not None
    assert _section_metadata(first, TutorContextSection.REVIEW).selected_count == 0
    assert _section_metadata(first, TutorContextSection.RECENT_MESSAGES).selected_count == 0
    assert _section_metadata(first, TutorContextSection.RECENT_MESSAGES).skipped_count == 0


def test_context_redacts_messages_and_evidence_and_checkpoint_stores_metadata_only() -> None:
    builder = TutorContextBuilder(estimator=OneTokenEstimator(), config=_config())
    context_input = TutorContextInput(
        run_id="tutor-run-1",
        conversation_id="conversation-1",
        input_revision=2,
        current_input=TutorContextSource("message-current", "你不是应该教我编程语言吗"),
        current_input_required=True,
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
    assert "你不是应该教我编程语言吗" not in checkpoint_json
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
    assert selected_message_ids == []  # required current input and system consume the two-token budget first
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


class CharacterTokenEstimator:
    def estimate_tokens(self, value: object) -> int:
        return max(1, len(str(value)))


class AlwaysTooLargeEstimator:
    def estimate_tokens(self, value: object) -> int:
        del value
        return 2


class ContentAwareEstimator:
    def estimate_tokens(self, value: object) -> int:
        return 3 if "turn-6" in str(value) else 1


def test_current_input_is_reserved_before_optional_context_and_never_repeated_as_history() -> None:
    context_input = TutorContextInput(
        run_id="tutor-run-current",
        conversation_id="conversation-current",
        input_revision=5,
        current_input=TutorContextSource("message-5", "我应该学哪些语言"),
        current_input_required=True,
        system_descriptors=(TutorContextSource("system", {"policy": "bounded"}),),
        active_plan=(TutorContextSource("plan", {"path": "stale-html"}),),
        recent_messages=(
            TutorContextSource("message-1", {"role": "user", "content": "我想做个网站"}),
            TutorContextSource("message-2", {"role": "assistant", "content": "先找图片"}),
            TutorContextSource("message-3", {"role": "user", "content": "我已经有了"}),
            TutorContextSource("message-4", {"role": "user", "content": "你不是应该教我编程语言吗"}),
        ),
    )

    selection = TutorContextBuilder(estimator=OneTokenEstimator(), config=_config(recent_limit=4)).build(
        context_input,
        token_budget=2,
    )

    assert selection.current_input is not None
    assert selection.current_input.content == "我应该学哪些语言"
    assert [item.source_id for item in selection.items] == ["system"]
    assert "message-5" not in [item.source_id for item in selection.items]
    assert selection.checkpoint_metadata.current_input is not None
    assert selection.checkpoint_metadata.current_input.source_id == "message-5"


def test_recent_message_limit_keeps_the_newest_bounded_suffix_in_chronological_order() -> None:
    messages = tuple(
        TutorContextSource(f"message-{index}", {"role": "user", "content": f"turn-{index}"})
        for index in range(1, 7)
    )
    context_input = TutorContextInput(
        run_id="tutor-run-history",
        conversation_id="conversation-history",
        input_revision=7,
        current_input=TutorContextSource("message-7", "latest-turn"),
        current_input_required=True,
        recent_messages=messages,
    )

    selection = TutorContextBuilder(estimator=OneTokenEstimator(), config=_config(recent_limit=4)).build(
        context_input,
        token_budget=8,
    )

    assert [item.source_id for item in selection.items] == ["message-3", "message-4", "message-5", "message-6"]
    assert _section_metadata(selection, TutorContextSection.RECENT_MESSAGES).skipped_count == 2


def test_tight_history_budget_keeps_newest_messages_then_restores_chronological_order() -> None:
    messages = tuple(
        TutorContextSource(f"message-{index}", {"role": "user", "content": f"turn-{index}"})
        for index in range(1, 7)
    )
    context_input = TutorContextInput(
        run_id="tutor-run-tight-history",
        conversation_id="conversation-tight-history",
        input_revision=7,
        current_input_required=True,
        current_input=TutorContextSource("message-7", "latest-turn"),
        recent_messages=messages,
    )

    selection = TutorContextBuilder(estimator=OneTokenEstimator(), config=_config(recent_limit=4)).build(
        context_input,
        token_budget=3,
    )

    assert [item.source_id for item in selection.items] == ["message-5", "message-6"]
    assert _section_metadata(selection, TutorContextSection.RECENT_MESSAGES).skipped_count == 4


def test_history_selection_skips_one_oversized_newest_item_and_keeps_the_next_newest() -> None:
    context_input = TutorContextInput(
        run_id="tutor-run-mixed-history",
        conversation_id="conversation-mixed-history",
        input_revision=7,
        current_input_required=True,
        current_input=TutorContextSource("message-7", "latest-turn"),
        recent_messages=tuple(
            TutorContextSource(f"message-{index}", {"role": "user", "content": f"turn-{index}"})
            for index in range(3, 7)
        ),
    )

    selection = TutorContextBuilder(estimator=ContentAwareEstimator(), config=_config(recent_limit=4)).build(
        context_input,
        token_budget=2,
    )

    assert [item.source_id for item in selection.items] == ["message-5"]
    assert _section_metadata(selection, TutorContextSection.RECENT_MESSAGES).skipped_count == 3


def test_oversized_current_input_is_deterministically_truncated_before_optional_context() -> None:
    context_input = TutorContextInput(
        run_id="tutor-run-truncate",
        conversation_id="conversation-truncate",
        input_revision=1,
        current_input=TutorContextSource("message-1", "abcdefghi"),
        current_input_required=True,
        system_descriptors=(TutorContextSource("system", "optional"),),
    )

    selection = TutorContextBuilder(
        estimator=CharacterTokenEstimator(),
        config=TutorContextBuilderConfig(max_source_characters=20),
    ).build(context_input, token_budget=5)

    assert selection.current_input is not None
    assert selection.current_input.content == "ab..."
    assert selection.current_input.truncated is True
    assert selection.items == ()
    assert selection.checkpoint_metadata.current_input is not None
    assert selection.checkpoint_metadata.current_input.truncated is True
    assert selection.checkpoint_metadata.truncated_count == 1


def test_selected_optional_source_truncation_is_counted_without_storing_raw_content() -> None:
    selection = TutorContextBuilder(
        estimator=OneTokenEstimator(),
        config=TutorContextBuilderConfig(max_source_characters=20),
    ).build(
        TutorContextInput(
            run_id="tutor-run-optional-truncate",
            conversation_id="conversation-optional-truncate",
            input_revision=1,
            current_input_required=True,
            current_input=TutorContextSource("message-1", "current"),
            activity_facts=(TutorContextSource("activity-1", "x" * 200),),
        ),
        token_budget=2,
    )

    assert selection.current_input is not None
    assert [item.source_id for item in selection.items] == ["activity-1"]
    assert selection.checkpoint_metadata.truncated_count == 1
    assert "x" * 200 not in json.dumps(selection.checkpoint_metadata.as_dict())


def test_current_input_hash_and_token_metadata_match_the_bounded_prompt_content() -> None:
    context_input = TutorContextInput(
        run_id="tutor-run-public-limit",
        conversation_id="conversation-public-limit",
        input_revision=1,
        current_input_required=True,
        current_input=TutorContextSource("message-1", "x" * 1700),
    )

    selection = TutorContextBuilder(
        estimator=CharacterTokenEstimator(),
        config=TutorContextBuilderConfig(max_source_characters=2000),
    ).build(context_input, token_budget=2000)

    assert selection.current_input is not None
    assert len(selection.current_input.content) == 1603
    assert selection.current_input.token_estimate == len(selection.current_input.content)
    assert selection.checkpoint_metadata.current_input is not None
    assert selection.checkpoint_metadata.current_input.source_hash == selection.current_input.source_hash


def test_proactive_context_contract_rejects_an_invented_current_input() -> None:
    with pytest.raises(TutorContextError) as exc_info:
        TutorContextInput(
            run_id="tutor-run-proactive",
            conversation_id="conversation-proactive",
            input_revision=0,
            current_input_required=False,
            current_input=TutorContextSource("invented", "invented learner text"),
        )

    assert exc_info.value.safe_code == "TUTOR_CURRENT_INPUT_UNEXPECTED"


def test_unrepresentable_required_current_input_raises_typed_context_error() -> None:
    context_input = TutorContextInput(
        run_id="tutor-run-fail",
        conversation_id="conversation-fail",
        input_revision=1,
        current_input=TutorContextSource("message-1", "x"),
        current_input_required=True,
    )

    with pytest.raises(TutorContextError) as exc_info:
        TutorContextBuilder(estimator=AlwaysTooLargeEstimator()).build(context_input, token_budget=1)

    assert exc_info.value.safe_code == "TUTOR_CURRENT_INPUT_UNREPRESENTABLE"
