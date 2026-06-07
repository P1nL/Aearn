from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, field_validator

from app.agents.runtime.guardrails import assert_safe_teaching_output
from app.services.llm.llm_client import LLMInvalidResponseError


MAX_LEARNING_OUTPUT_BYTES = 32_000
MAX_PUBLIC_MESSAGE_CHARS = 4_000

LEARNING_PUBLIC_OUTPUT_INSTRUCTIONS = """你必须只输出一个 JSON object，不要 Markdown，不要额外解释。

JSON 必须严格符合：
{
  "schema_version": "1",
  "public_message": "直接展示给学习者的正文",
  "internal_review": {
    "public_message_safe": true,
    "no_internal_policy_reference": true,
    "no_answer_leakage": true,
    "no_forbidden_content": true
  }
}

要求：
- public_message 是唯一给学习者看的正文，必须自然、具体、非空。
- internal_review 只能包含上面四个布尔字段，不能包含 reason、analysis、thoughts 或任何自由文本。
- 如果 public_message 不安全、包含内部策略自述、泄露答案或泄露不可展示内容，internal_review 对应字段必须为 false。
"""


class LearningOutputReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_message_safe: StrictBool
    no_internal_policy_reference: StrictBool
    no_answer_leakage: StrictBool
    no_forbidden_content: StrictBool

    def assert_all_true(self) -> None:
        if not (
            self.public_message_safe
            and self.no_internal_policy_reference
            and self.no_answer_leakage
            and self.no_forbidden_content
        ):
            raise LLMInvalidResponseError("Learning structured output self-review failed")


class LearningPublicOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"]
    public_message: str = Field(min_length=1, max_length=MAX_PUBLIC_MESSAGE_CHARS)
    internal_review: LearningOutputReview

    @field_validator("public_message")
    @classmethod
    def public_message_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("public_message must not be blank")
        return stripped


class LearningOutputStreamDecoder:
    def __init__(self, *, max_chars: int = MAX_LEARNING_OUTPUT_BYTES) -> None:
        self._raw = ""
        self._emitted_public_message = ""
        self._max_chars = max_chars

    @property
    def raw_text(self) -> str:
        return self._raw

    @property
    def emitted_public_message(self) -> str:
        return self._emitted_public_message

    def feed(self, chunk: str) -> list[str]:
        if not chunk:
            return []
        self._raw += chunk
        if len(self._raw) > self._max_chars:
            raise LLMInvalidResponseError("Learning structured output exceeded size limit")

        public_prefix, _complete = _scan_public_message_prefix(self._raw)
        if len(public_prefix) < len(self._emitted_public_message):
            raise LLMInvalidResponseError("Learning structured output public_message changed during streaming")
        delta = public_prefix[len(self._emitted_public_message) :]
        self._emitted_public_message = public_prefix
        return [delta] if delta else []

    def finish(self) -> LearningPublicOutput:
        output = parse_learning_public_output(self._raw)
        if self._emitted_public_message != output.public_message:
            raise LLMInvalidResponseError("Learning structured output stream did not match final public_message")
        return output


def parse_learning_public_output(raw_text: str) -> LearningPublicOutput:
    raw = raw_text.strip()
    if not raw:
        raise LLMInvalidResponseError("Learning structured output was empty")
    try:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicate_object_keys)
    except (json.JSONDecodeError, ValueError) as exc:
        raise LLMInvalidResponseError("Learning structured output was invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise LLMInvalidResponseError("Learning structured output must be a JSON object")
    try:
        output = LearningPublicOutput.model_validate(payload)
    except ValidationError as exc:
        raise LLMInvalidResponseError("Learning structured output failed schema validation") from exc
    output.internal_review.assert_all_true()
    assert_safe_teaching_output(output.public_message)
    return output


def learning_public_output_json(public_message: str) -> str:
    return json.dumps(
        {
            "schema_version": "1",
            "public_message": public_message,
            "internal_review": {
                "public_message_safe": True,
                "no_internal_policy_reference": True,
                "no_answer_leakage": True,
                "no_forbidden_content": True,
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _reject_duplicate_object_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _scan_public_message_prefix(raw: str) -> tuple[str, bool]:
    index = _skip_whitespace(raw, 0)
    if index >= len(raw):
        return "", False
    if raw[index] != "{":
        return "", False
    index += 1
    decoder = json.JSONDecoder()

    while True:
        index = _skip_whitespace(raw, index)
        if index >= len(raw):
            return "", False
        if raw[index] == "}":
            return "", False
        if raw[index] != '"':
            return "", False
        key, index, complete_key = _parse_json_string_prefix(raw, index)
        if not complete_key:
            return "", False
        index = _skip_whitespace(raw, index)
        if index >= len(raw):
            return "", False
        if raw[index] != ":":
            raise LLMInvalidResponseError("Learning structured output object key was not followed by ':'")
        index += 1
        index = _skip_whitespace(raw, index)
        if index >= len(raw):
            return "", False
        if key == "public_message":
            if raw[index] != '"':
                raise LLMInvalidResponseError("Learning structured output public_message must be a string")
            public_message, _value_end, complete = _parse_json_string_prefix(raw, index)
            return public_message, complete
        try:
            _value, index = decoder.raw_decode(raw, index)
        except json.JSONDecodeError:
            return "", False
        index = _skip_whitespace(raw, index)
        if index >= len(raw):
            return "", False
        if raw[index] == ",":
            index += 1
            continue
        if raw[index] == "}":
            return "", False
        raise LLMInvalidResponseError("Learning structured output object member was malformed")


def _skip_whitespace(text: str, index: int) -> int:
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    return index


def _parse_json_string_prefix(text: str, index: int) -> tuple[str, int, bool]:
    if index >= len(text) or text[index] != '"':
        raise LLMInvalidResponseError("Expected JSON string")
    chars: list[str] = []
    cursor = index + 1
    while cursor < len(text):
        char = text[cursor]
        if char == '"':
            return "".join(chars), cursor + 1, True
        if char == "\\":
            parsed = _parse_escape_prefix(text, cursor)
            if parsed is None:
                return "".join(chars), cursor, False
            decoded, cursor = parsed
            chars.append(decoded)
            continue
        if ord(char) < 0x20:
            raise LLMInvalidResponseError("Learning structured output string contained a control character")
        chars.append(char)
        cursor += 1
    return "".join(chars), cursor, False


def _parse_escape_prefix(text: str, index: int) -> tuple[str, int] | None:
    if index + 1 >= len(text):
        return None
    escape = text[index + 1]
    simple = {
        '"': '"',
        "\\": "\\",
        "/": "/",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
    }
    if escape in simple:
        return simple[escape], index + 2
    if escape != "u":
        raise LLMInvalidResponseError("Learning structured output string contained an invalid escape")
    if index + 6 > len(text):
        return None
    code = _parse_hex_escape(text[index + 2 : index + 6])
    cursor = index + 6
    if 0xD800 <= code <= 0xDBFF:
        if cursor >= len(text):
            return None
        if text[cursor] == "\\":
            if cursor + 1 >= len(text):
                return None
            if text[cursor + 1] == "u":
                if cursor + 6 > len(text):
                    return None
                low = _parse_hex_escape(text[cursor + 2 : cursor + 6])
                if 0xDC00 <= low <= 0xDFFF:
                    combined = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)
                    return chr(combined), cursor + 6
        return chr(code), cursor
    return chr(code), cursor


def _parse_hex_escape(value: str) -> int:
    if len(value) != 4 or any(char not in "0123456789abcdefABCDEF" for char in value):
        raise LLMInvalidResponseError("Learning structured output string contained an invalid unicode escape")
    return int(value, 16)
