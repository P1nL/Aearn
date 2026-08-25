from __future__ import annotations

import json

import pytest

from app.services.llm.llm_client import _parse_responses_stream
from app.services.tutor.public_thinking_stream import (
    TutorProviderPublicTextProjector,
    TutorPublicThinkingSafetyError,
    TutorPublicThinkingStreamError,
)


class RecordingSink:
    def __init__(self) -> None:
        self.operations: list[tuple[str, int, str]] = []

    def begin_attempt(self, attempt_index: int) -> None:
        self.operations.append(("begin", attempt_index, ""))

    def append_text(self, attempt_index: int, text: str) -> None:
        self.operations.append(("append", attempt_index, text))

    def complete_attempt(self, attempt_index: int) -> None:
        self.operations.append(("complete", attempt_index, ""))

    def reset_attempt(self, attempt_index: int) -> None:
        self.operations.append(("reset", attempt_index, ""))

    def discard_attempt(self, attempt_index: int) -> None:
        self.operations.append(("discard", attempt_index, ""))

    def discard_current(self) -> None:
        self.operations.append(("discard_current", 0, ""))


def _provider_json(thinking: str, *, answer: str = "最终回答") -> str:
    return json.dumps(
        {
            "schema_version": "tutor_provider_items_v4",
            "message": {
                "type": "agent_message",
                "public_thinking_text": thinking,
                "text": answer,
                "conversation_title": None,
            },
            "action": {"type": "turn_completed"},
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )


def test_projector_decodes_exact_public_text_across_single_character_chunks() -> None:
    expected = '先看 "scope"\n再看路径 \\ 与 emoji 😀。'
    sink = RecordingSink()
    projector = TutorProviderPublicTextProjector(attempt_index=1, sink=sink)

    for character in _provider_json(expected):
        projector.on_text_delta(character)
    projector.on_stream_complete()

    assert projector.text == expected
    assert projector.saw_target is True
    assert "".join(text for operation, _attempt, text in sink.operations if operation == "append") == expected
    assert all(operation != "complete" for operation, _attempt, _text in sink.operations)


def test_projector_handles_unicode_escape_split_before_first_hex_digit_and_surrogate_pair() -> None:
    sink = RecordingSink()
    projector = TutorProviderPublicTextProjector(attempt_index=2, sink=sink)
    payload = _provider_json("你好😀")
    split_at = payload.index("\\u4f60") + 2

    projector.on_text_delta(payload[:split_at])
    projector.on_text_delta(payload[split_at:])
    projector.on_stream_complete()

    assert projector.text == "你好😀"


def test_projector_restart_resets_parser_and_published_text() -> None:
    sink = RecordingSink()
    projector = TutorProviderPublicTextProjector(attempt_index=1, sink=sink)
    first = _provider_json("first.")
    cut = first.index("first.") + len("first.")

    projector.on_text_delta(first[:cut])
    projector.on_stream_restart()
    projector.on_text_delta(_provider_json("第二段。"))
    projector.on_stream_complete()

    assert projector.text == "第二段。"
    assert ("reset", 1, "") in sink.operations


@pytest.mark.parametrize(
    "payload",
    [
        '{"message":{"public_thinking_text":1}}',
        '{"message":{"public_thinking_text":"one","public_thinking_text":"two"}}',
        '{"message":{"text":"answer"}}',
        '[{"message":{"public_thinking_text":"text"}}]',
    ],
)
def test_projector_fails_closed_for_missing_duplicate_or_invalid_target(payload: str) -> None:
    projector = TutorProviderPublicTextProjector(attempt_index=1)
    with pytest.raises(TutorPublicThinkingStreamError):
        projector.on_text_delta(payload)
        projector.on_stream_complete()


def test_projector_checks_cumulative_public_prefix_before_append() -> None:
    projector = TutorProviderPublicTextProjector(attempt_index=1)
    with pytest.raises(TutorPublicThinkingSafetyError):
        projector.on_text_delta(_provider_json("raw prompt summary。"))


class ExplodingObserver:
    def on_stream_start(self) -> None:
        return

    def on_text_delta(self, delta: str) -> None:
        del delta
        raise RuntimeError("observer stopped the stream")

    def on_stream_restart(self) -> None:
        return

    def on_stream_complete(self) -> None:
        return


def test_responses_parser_propagates_visible_observer_failure() -> None:
    frames = [
        b'data: {"type":"response.output_text.delta","delta":"visible"}\n',
        b"\n",
    ]

    with pytest.raises(RuntimeError, match="observer stopped the stream"):
        _parse_responses_stream(frames, visible_output_observer=ExplodingObserver())


def test_responses_parser_forwards_only_output_text_delta_to_observer() -> None:
    sink = RecordingSink()
    projector = TutorProviderPublicTextProjector(attempt_index=1, sink=sink)
    visible = _provider_json("公开文本。")
    frames = [
        b'data: {"type":"response.reasoning_text.delta","delta":"private"}\n',
        b'\n',
        f'data: {json.dumps({"type": "response.output_text.delta", "delta": visible})}\n'.encode(),
        b'\n',
        f'data: {json.dumps({"type": "response.completed", "response": {"status": "completed", "output": []}})}\n'.encode(),
        b'\n',
    ]

    _parse_responses_stream(frames, visible_output_observer=projector)
    projector.on_stream_complete()

    assert projector.text == "公开文本。"
    assert "private" not in projector.text
