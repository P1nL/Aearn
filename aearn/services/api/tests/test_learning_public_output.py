import json

import pytest

from app.agents.learning.learning_public_output import (
    LearningOutputStreamDecoder,
    learning_public_output_json,
    parse_learning_public_output,
)
from app.services.llm.llm_client import LLMInvalidResponseError


def _decode_chunks(chunks: list[str]) -> tuple[list[str], str]:
    decoder = LearningOutputStreamDecoder()
    deltas: list[str] = []
    for chunk in chunks:
        deltas.extend(decoder.feed(chunk))
    output = decoder.finish()
    return deltas, output.public_message


def test_learning_output_decoder_streams_public_message_one_character_at_a_time() -> None:
    raw = learning_public_output_json("先看 count 的作用域。")

    deltas, public_message = _decode_chunks(list(raw))

    assert "".join(deltas) == "先看 count 的作用域。"
    assert public_message == "先看 count 的作用域。"


def test_learning_output_decoder_handles_escapes_and_unicode_chunk_boundaries() -> None:
    raw = learning_public_output_json('先看 "count"\\state\n再看事件。')
    chunks = [raw[:42], raw[42:59], raw[59:]]

    deltas, public_message = _decode_chunks(chunks)

    assert "".join(deltas) == '先看 "count"\\state\n再看事件。'
    assert public_message == '先看 "count"\\state\n再看事件。'


def test_learning_output_decoder_handles_unicode_escape_split_across_chunks() -> None:
    raw = (
        '{"schema_version":"1","public_message":"\\u5148\\u770b count",'
        '"internal_review":{"public_message_safe":true,'
        '"no_internal_policy_reference":true,"no_answer_leakage":true,'
        '"no_forbidden_content":true}}'
    )

    deltas, public_message = _decode_chunks([raw[:43], raw[43:47], raw[47:]])

    assert "".join(deltas) == "先看 count"
    assert public_message == "先看 count"


def test_learning_output_decoder_handles_public_message_after_other_fields() -> None:
    raw = json.dumps(
        {
            "schema_version": "1",
            "internal_review": {
                "public_message_safe": True,
                "no_internal_policy_reference": True,
                "no_answer_leakage": True,
                "no_forbidden_content": True,
            },
            "public_message": "字段顺序变化也只流正文。",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )

    deltas, public_message = _decode_chunks([raw[:20], raw[20:80], raw[80:]])

    assert "".join(deltas) == "字段顺序变化也只流正文。"
    assert public_message == "字段顺序变化也只流正文。"


def test_learning_output_rejects_false_internal_review() -> None:
    raw = learning_public_output_json("看一个局部提示。").replace('"no_answer_leakage":true', '"no_answer_leakage":false')

    with pytest.raises(LLMInvalidResponseError):
        parse_learning_public_output(raw)


def test_learning_output_rejects_non_boolean_internal_review() -> None:
    raw = learning_public_output_json("看一个局部提示。").replace(
        '"public_message_safe":true',
        '"public_message_safe":"true"',
    )

    with pytest.raises(LLMInvalidResponseError):
        parse_learning_public_output(raw)


def test_learning_output_rejects_duplicate_public_message_key() -> None:
    raw = (
        '{"schema_version":"1","public_message":"第一段","public_message":"第二段",'
        '"internal_review":{"public_message_safe":true,'
        '"no_internal_policy_reference":true,"no_answer_leakage":true,'
        '"no_forbidden_content":true}}'
    )

    with pytest.raises(LLMInvalidResponseError):
        parse_learning_public_output(raw)


def test_learning_output_rejects_diagnostic_summary_field() -> None:
    raw = learning_public_output_json("只展示正式正文。").replace(
        '"internal_review"',
        '"diagnostic_summary":"不要展示","internal_review"',
    )

    with pytest.raises(LLMInvalidResponseError):
        parse_learning_public_output(raw)


def test_learning_output_rejects_policy_leak_in_public_message() -> None:
    raw = learning_public_output_json("_policy说这样符合policy要求。")

    with pytest.raises(LLMInvalidResponseError):
        parse_learning_public_output(raw)


def test_learning_output_decoder_rejects_truncated_stream_on_finish() -> None:
    decoder = LearningOutputStreamDecoder()
    decoder.feed('{"schema_version":"1","public_message":"只发了半段')

    with pytest.raises(LLMInvalidResponseError):
        decoder.finish()


def test_learning_output_decoder_rejects_oversized_stream() -> None:
    decoder = LearningOutputStreamDecoder(max_chars=10)

    with pytest.raises(LLMInvalidResponseError):
        decoder.feed('{"schema_version":"1"}')
