"""Incremental projection of learner-safe public thinking from strict provider JSON."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from app.agents.harness.contracts import MAX_TUTOR_PUBLIC_THINKING_TEXT_LENGTH
from app.core.teaching_safety import check_teaching_output
from app.services.llm.llm_client import LLMVisibleOutputObserver


PUBLIC_THINKING_CHUNK_MAX_LENGTH = 160
_BOUNDARY_CHARACTERS = frozenset("\n。！？.!?；;")


class TutorPublicThinkingStreamError(ValueError):
    """A visible JSON stream cannot be projected safely or deterministically."""


class TutorPublicThinkingSafetyError(TutorPublicThinkingStreamError):
    """A cumulative public thinking prefix failed teaching-output safety."""


class TutorPublicThinkingSink(Protocol):
    def begin_attempt(self, attempt_index: int) -> None: ...

    def append_text(self, attempt_index: int, text: str) -> None: ...

    def complete_attempt(self, attempt_index: int) -> None: ...

    def reset_attempt(self, attempt_index: int) -> None: ...

    def discard_attempt(self, attempt_index: int) -> None: ...

    def discard_current(self) -> None: ...


class _NoopPublicThinkingSink:
    def begin_attempt(self, attempt_index: int) -> None:
        del attempt_index

    def append_text(self, attempt_index: int, text: str) -> None:
        del attempt_index, text

    def complete_attempt(self, attempt_index: int) -> None:
        del attempt_index

    def reset_attempt(self, attempt_index: int) -> None:
        del attempt_index

    def discard_attempt(self, attempt_index: int) -> None:
        del attempt_index

    def discard_current(self) -> None:
        return


@dataclass
class _Container:
    kind: Literal["object", "array"]
    path: tuple[str, ...]
    expect: str
    key: str | None = None
    index: int = 0


class TutorProviderPublicTextProjector(LLMVisibleOutputObserver):
    """Decode only ``message.public_thinking_text`` while JSON text is streaming."""

    _TARGET_PATH = ("message", "public_thinking_text")

    def __init__(self, *, attempt_index: int, sink: TutorPublicThinkingSink | None = None) -> None:
        self._attempt_index = attempt_index
        self._sink = sink or _NoopPublicThinkingSink()
        self._chunker = _PublicThinkingChunker(attempt_index=attempt_index, sink=self._sink)
        self._reset_parser()

    @property
    def text(self) -> str:
        return self._chunker.text

    @property
    def saw_target(self) -> bool:
        return self._target_seen

    def on_stream_start(self) -> None:
        return

    def on_stream_restart(self) -> None:
        self._sink.reset_attempt(self._attempt_index)
        self._chunker = _PublicThinkingChunker(attempt_index=self._attempt_index, sink=self._sink)
        self._reset_parser()

    def on_text_delta(self, delta: str) -> None:
        for character in delta:
            self._consume(character)

    def on_stream_complete(self) -> None:
        if self._in_string or self._unicode_digits is not None or self._scalar_buffer:
            raise TutorPublicThinkingStreamError("provider JSON stream ended inside a token")
        if self._stack or not self._root_complete:
            raise TutorPublicThinkingStreamError("provider JSON stream did not complete one root object")
        if not self._target_seen or not self._target_complete:
            raise TutorPublicThinkingStreamError("public_thinking_text was not completed in provider JSON")
        self._chunker.finish_provider_stream()

    def _reset_parser(self) -> None:
        self._stack: list[_Container] = []
        self._root_started = False
        self._root_complete = False
        self._in_string = False
        self._string_role: Literal["key", "value"] | None = None
        self._string_path: tuple[str, ...] = ()
        self._string_value: list[str] = []
        self._escape = False
        self._unicode_digits: str | None = None
        self._pending_high_surrogate: int | None = None
        self._scalar_buffer = ""
        self._target_active = False
        self._target_seen = False
        self._target_complete = False

    def _consume(self, character: str) -> None:
        if self._in_string:
            self._consume_string(character)
            return
        if self._scalar_buffer:
            if character in " \t\r\n,]}":
                self._finish_scalar()
                self._consume(character)
            else:
                self._scalar_buffer += character
            return
        if character in " \t\r\n":
            return
        if not self._root_started:
            if character != "{":
                raise TutorPublicThinkingStreamError("provider JSON root must be an object")
            self._root_started = True
            self._start_value(character, ())
            return
        if not self._stack:
            raise TutorPublicThinkingStreamError("provider JSON has content after the root value")
        context = self._stack[-1]
        if context.kind == "object":
            self._consume_object(context, character)
        else:
            self._consume_array(context, character)

    def _consume_object(self, context: _Container, character: str) -> None:
        if context.expect == "key_or_end":
            if character == "}":
                self._close_container()
                return
            if character != '"':
                raise TutorPublicThinkingStreamError("provider JSON object expected a key")
            self._start_string(role="key", path=context.path)
            return
        if context.expect == "colon":
            if character != ":":
                raise TutorPublicThinkingStreamError("provider JSON object expected a colon")
            context.expect = "value"
            return
        if context.expect == "value":
            if context.key is None:
                raise TutorPublicThinkingStreamError("provider JSON object value has no key")
            self._start_value(character, (*context.path, context.key))
            return
        if context.expect == "comma_or_end":
            if character == ",":
                context.expect = "key_or_end"
                context.key = None
                return
            if character == "}":
                self._close_container()
                return
        raise TutorPublicThinkingStreamError("provider JSON object delimiter is invalid")

    def _consume_array(self, context: _Container, character: str) -> None:
        if context.expect == "value_or_end":
            if character == "]":
                self._close_container()
                return
            self._start_value(character, (*context.path, str(context.index)))
            return
        if context.expect == "comma_or_end":
            if character == ",":
                context.index += 1
                context.expect = "value_or_end"
                return
            if character == "]":
                self._close_container()
                return
        raise TutorPublicThinkingStreamError("provider JSON array delimiter is invalid")

    def _start_value(self, character: str, path: tuple[str, ...]) -> None:
        if path == self._TARGET_PATH and self._target_seen:
            raise TutorPublicThinkingStreamError("public_thinking_text appeared more than once")
        if character == "{":
            if path == self._TARGET_PATH:
                raise TutorPublicThinkingStreamError("public_thinking_text must be a string")
            self._stack.append(_Container(kind="object", path=path, expect="key_or_end"))
            return
        if character == "[":
            if path == self._TARGET_PATH:
                raise TutorPublicThinkingStreamError("public_thinking_text must be a string")
            self._stack.append(_Container(kind="array", path=path, expect="value_or_end"))
            return
        if character == '"':
            self._start_string(role="value", path=path)
            if path == self._TARGET_PATH:
                self._target_seen = True
                self._target_active = True
            return
        if path == self._TARGET_PATH:
            raise TutorPublicThinkingStreamError("public_thinking_text must be a string")
        if character in "-0123456789tfn":
            self._scalar_buffer = character
            return
        raise TutorPublicThinkingStreamError("provider JSON value is invalid")

    def _start_string(self, *, role: Literal["key", "value"], path: tuple[str, ...]) -> None:
        self._in_string = True
        self._string_role = role
        self._string_path = path
        self._string_value = []
        self._escape = False
        self._unicode_digits = None
        self._pending_high_surrogate = None

    def _consume_string(self, character: str) -> None:
        if self._unicode_digits is not None:
            if character not in "0123456789abcdefABCDEF":
                raise TutorPublicThinkingStreamError("provider JSON contains an invalid Unicode escape")
            self._unicode_digits += character
            if len(self._unicode_digits) == 4:
                self._emit_unicode_escape(int(self._unicode_digits, 16))
                self._unicode_digits = None
                self._escape = False
            return
        if self._escape:
            if character == "u":
                self._unicode_digits = ""
                return
            mapping = {
                '"': '"',
                "\\": "\\",
                "/": "/",
                "b": "\b",
                "f": "\f",
                "n": "\n",
                "r": "\r",
                "t": "\t",
            }
            decoded = mapping.get(character)
            if decoded is None:
                raise TutorPublicThinkingStreamError("provider JSON contains an invalid escape")
            self._emit_string_character(decoded)
            self._escape = False
            return
        if character == "\\":
            self._escape = True
            return
        if character == '"':
            if self._pending_high_surrogate is not None:
                raise TutorPublicThinkingStreamError("provider JSON contains an unmatched surrogate")
            self._finish_string()
            return
        if ord(character) < 0x20:
            raise TutorPublicThinkingStreamError("provider JSON string contains a control character")
        self._emit_string_character(character)

    def _emit_unicode_escape(self, code_unit: int) -> None:
        if 0xD800 <= code_unit <= 0xDBFF:
            if self._pending_high_surrogate is not None:
                raise TutorPublicThinkingStreamError("provider JSON contains consecutive high surrogates")
            self._pending_high_surrogate = code_unit
            return
        if 0xDC00 <= code_unit <= 0xDFFF:
            if self._pending_high_surrogate is None:
                raise TutorPublicThinkingStreamError("provider JSON contains an unmatched low surrogate")
            code_point = 0x10000 + ((self._pending_high_surrogate - 0xD800) << 10) + (code_unit - 0xDC00)
            self._pending_high_surrogate = None
            self._emit_string_character(chr(code_point))
            return
        if self._pending_high_surrogate is not None:
            raise TutorPublicThinkingStreamError("provider JSON high surrogate is not followed by a low surrogate")
        self._emit_string_character(chr(code_unit))

    def _emit_string_character(self, character: str) -> None:
        if self._pending_high_surrogate is not None:
            raise TutorPublicThinkingStreamError(
                "provider JSON high surrogate is not followed by a low surrogate"
            )
        self._string_value.append(character)
        if self._target_active:
            self._chunker.feed(character)

    def _finish_string(self) -> None:
        value = "".join(self._string_value)
        role = self._string_role
        path = self._string_path
        target = self._target_active
        self._in_string = False
        self._string_role = None
        self._string_path = ()
        self._string_value = []
        self._escape = False
        self._target_active = False
        if role == "key":
            context = self._stack[-1]
            if context.kind != "object" or context.expect != "key_or_end":
                raise TutorPublicThinkingStreamError("provider JSON key is out of place")
            context.key = value
            context.expect = "colon"
            return
        if role != "value":
            raise TutorPublicThinkingStreamError("provider JSON string role is invalid")
        if target:
            self._target_complete = True
        self._finish_value(path)

    def _finish_scalar(self) -> None:
        token = self._scalar_buffer
        self._scalar_buffer = ""
        if token not in {"true", "false", "null"}:
            try:
                float(token)
            except ValueError as exc:
                raise TutorPublicThinkingStreamError("provider JSON scalar is invalid") from exc
        self._finish_value(self._current_value_path())

    def _current_value_path(self) -> tuple[str, ...]:
        if not self._stack:
            return ()
        context = self._stack[-1]
        if context.kind == "object":
            return (*context.path, context.key or "")
        return (*context.path, str(context.index))

    def _close_container(self) -> None:
        context = self._stack.pop()
        self._finish_value(context.path)

    def _finish_value(self, path: tuple[str, ...]) -> None:
        del path
        if not self._stack:
            self._root_complete = True
            return
        parent = self._stack[-1]
        parent.expect = "comma_or_end"


class _PublicThinkingChunker:
    def __init__(self, *, attempt_index: int, sink: TutorPublicThinkingSink) -> None:
        self._attempt_index = attempt_index
        self._sink = sink
        self._published = ""
        self._candidate = ""
        self._provider_stream_finished = False

    @property
    def text(self) -> str:
        return self._published + self._candidate

    def feed(self, character: str) -> None:
        if self._provider_stream_finished:
            raise TutorPublicThinkingStreamError("public thinking text arrived after provider stream completion")
        self._candidate += character
        if len(self.text) > MAX_TUTOR_PUBLIC_THINKING_TEXT_LENGTH:
            raise TutorPublicThinkingStreamError("public thinking text exceeds the configured bound")
        if character in _BOUNDARY_CHARACTERS or len(self._candidate) >= PUBLIC_THINKING_CHUNK_MAX_LENGTH:
            self._flush()

    def finish_provider_stream(self) -> None:
        if self._provider_stream_finished:
            return
        self._flush()
        if not self._published.strip():
            raise TutorPublicThinkingStreamError("public thinking text is empty")
        self._provider_stream_finished = True

    def _flush(self) -> None:
        if not self._candidate:
            return
        cumulative = self._published + self._candidate
        check = check_teaching_output(cumulative)
        if check.blocked:
            raise TutorPublicThinkingSafetyError("public thinking prefix failed teaching safety")
        delta = self._candidate
        self._candidate = ""
        self._published = cumulative
        self._sink.append_text(self._attempt_index, delta)
