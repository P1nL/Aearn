"""Bounded, inert parsing of unreviewed candidate captures.

This pure module neither fetches nor authorizes storage or corpus admission.
Callers must attest a complete capture after transport checks. Output is untrusted.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal

FragmentKind = Literal["heading", "paragraph", "list_item", "table_row", "code"]
MAX_BODY_BYTES = 1_000_000
MAX_FRAGMENTS = 512
MAX_FRAGMENT_CHARS = 16_384
_MEDIA_TYPES = {"text/html", "text/markdown", "text/plain"}
_MARKUP = re.compile(r"<\s*!?/?\s*[a-z][^>]{0,1024}>", re.I)
_LIST = re.compile(r"^(\s{0,12})([-+*]|[0-9]{1,6}[.)])\s+(.+)$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})[^`]*$")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")


class CandidateParseError(ValueError):
    """Fixed-code failure; candidate content must not leak into errors."""


@dataclass(frozen=True, slots=True)
class CandidateFragment:
    ordinal: int
    kind: FragmentKind
    text: str
    depth: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ParsedCandidateDocument:
    media_type: str
    body_sha256: str  # Exact full-capture bytes, never a snippet or decoded-text hash.
    fragments: tuple[CandidateFragment, ...]


class _Fragments:
    def __init__(self) -> None:
        self.items: list[CandidateFragment] = []
        self.total_chars = 0

    def add(self, kind: FragmentKind, text: str, *, depth: int = 0) -> None:
        text = text.strip("\r\n") if kind == "code" else text.strip()
        if not text:
            return
        if (len(self.items) >= MAX_FRAGMENTS or len(text) > MAX_FRAGMENT_CHARS
                or self.total_chars + len(text) > MAX_BODY_BYTES):
            raise CandidateParseError("content_limit")
        self.total_chars += len(text)
        ordinal = len(self.items)
        digest = hashlib.sha256(f"candidate-fragment-v1\0{ordinal}\0{kind}\0{depth}\0{text}".encode()).hexdigest()
        self.items.append(CandidateFragment(ordinal, kind, text, depth, digest))


class _CandidateHTMLParser(HTMLParser):
    _SKIP = {"head", "script", "style", "template", "noscript", "svg", "math",
             "iframe", "object", "form", "nav", "footer", "aside"}
    _BREAK = {"p", "div", "section", "article", "blockquote", "hr"}

    def __init__(self, output: _Fragments) -> None:
        super().__init__(convert_charrefs=True)
        self.output = output
        self.skip: list[str] = []
        self.lists: list[tuple[str, int]] = []
        self.active: str | None = None
        self.parts: list[str] = []
        self.paragraph: list[str] = []
        self.row: list[str] | None = None
        self.row_header = False
        self.open_pre = False
        self.open_table = False

    def _flush_paragraph(self) -> None:
        self.output.add("paragraph", "".join(self.paragraph))
        self.paragraph = []

    def _finish(self) -> None:
        if self.active is None:
            return
        tag, text = self.active, "".join(self.parts)
        if tag == "pre":
            self.output.add("code", text)
        elif tag == "li":
            if self.lists:
                list_kind, count = self.lists[-1]
                prefix = f"{count}. " if list_kind == "ol" else "- "
                self.lists[-1] = (list_kind, count + 1)
                self.output.add("list_item", prefix + text.strip(), depth=len(self.lists))
        elif tag in {"td", "th"} and self.row is not None:
            self.row.append(text.strip().replace("|", "\\|"))
            self.row_header = self.row_header or tag == "th"
        elif tag.startswith("h"):
            self.output.add("heading", text, depth=int(tag[1]))
        else:
            self.output.add("paragraph", text)
        self.active, self.parts = None, []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skip:
            if tag in self._SKIP:
                self.skip.append(tag)
            return
        if tag in self._SKIP:
            self._flush_paragraph()
            self.skip.append(tag)
        elif tag == "br":
            (self.parts if self.active else self.paragraph).append("\n")
        elif tag in self._BREAK:
            if self.active is None:
                self._flush_paragraph()
        elif tag in {"ul", "ol"}:
            self._finish()
            self._flush_paragraph()
            self.lists.append((tag, 1))
        elif tag == "table":
            self._finish()
            self._flush_paragraph()
            self.open_table = True
        elif tag == "tr" and self.open_table:
            self._finish()
            self.row = []
            self.row_header = False
        elif tag in {"td", "th"} and self.row is not None:
            self._finish()
            self.active, self.parts = tag, []
        elif tag == "pre":
            self._finish()
            self._flush_paragraph()
            self.active, self.parts, self.open_pre = tag, [], True
        elif tag == "li" and self.lists or re.fullmatch(r"h[1-6]", tag):
            self._finish()
            self._flush_paragraph()
            self.active, self.parts = tag, []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag != "br":
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.skip:
            if tag in self.skip:
                while self.skip:
                    if self.skip.pop() == tag:
                        break
            return
        if tag == "pre":
            if self.active == "pre":
                self._finish()
            self.open_pre = False
        elif tag == self.active:
            self._finish()
        elif tag == "tr" and self.row is not None:
            self._finish()
            if self.row:
                self.output.add("table_row", "| " + " | ".join(self.row) + " |",
                                depth=int(self.row_header))
            self.row = None
        elif tag == "table":
            self.open_table = False
        elif tag in {"ul", "ol"} and self.lists:
            self._finish()
            self.lists.pop()
        elif tag in self._BREAK:
            self._flush_paragraph()

    def handle_data(self, data: str) -> None:
        if not self.skip:
            (self.parts if self.active else self.paragraph).append(data)

    def finish(self) -> None:
        self.close()
        if self.rawdata or self.open_pre or self.open_table or self.row is not None or self.skip:
            raise CandidateParseError("incomplete_markup")
        self._finish()
        self._flush_paragraph()


def _cells(line: str) -> list[str]:
    return [cell.strip().replace("\\|", "|").replace("|", "\\|")
            for cell in line.strip().strip("|").split("|")]


def _parse_lines(text: str, output: _Fragments, *, markdown: bool) -> None:
    lines = text.splitlines()
    paragraph: list[str] = []
    i = 0

    def flush() -> None:
        output.add("paragraph", "\n".join(paragraph))
        paragraph.clear()

    while i < len(lines):
        line = lines[i]
        if markdown and (match := _FENCE.match(line)):
            flush()
            marker = match.group(1)
            code: list[str] = []
            i += 1
            while i < len(lines) and not re.fullmatch(
                rf"\s*{re.escape(marker[0])}{{{len(marker)},}}\s*", lines[i]
            ):
                code.append(lines[i])
                i += 1
            if i == len(lines):
                raise CandidateParseError("incomplete_code_fence")
            output.add("code", "\n".join(code))
        elif markdown and (match := re.match(r"^(#{1,6})\s+(.+)$", line)):
            flush()
            output.add("heading", match.group(2), depth=len(match.group(1)))
        elif i + 1 < len(lines) and "|" in line and _TABLE_RULE.match(lines[i + 1]):
            flush()
            width = len(_cells(line))
            if width != len(_cells(lines[i + 1])):
                raise CandidateParseError("invalid_table")
            output.add("table_row", "| " + " | ".join(_cells(line)) + " |", depth=1)
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                cells = _cells(lines[i])
                if len(cells) != width:
                    raise CandidateParseError("invalid_table")
                output.add("table_row", "| " + " | ".join(cells) + " |")
                i += 1
            continue
        elif match := _LIST.match(line):
            flush()
            output.add("list_item", match.group(2) + " " + match.group(3),
                       depth=len(match.group(1)) // 2 + 1)
        elif line.startswith("    ") and not paragraph:
            flush()
            code = []
            while i < len(lines) and (lines[i].startswith("    ") or not lines[i].strip()):
                code.append(lines[i][4:] if lines[i].startswith("    ") else "")
                i += 1
            output.add("code", "\n".join(code))
            continue
        elif not line.strip():
            flush()
        else:
            paragraph.append(line)
        i += 1
    flush()


def _media_type(value: str) -> str:
    if type(value) is not str or len(value) > 256:
        raise CandidateParseError("unsupported_media_type")
    parts = value.split(";")
    media_type = parts[0].strip().lower()
    if media_type not in _MEDIA_TYPES or len(parts) > 2:
        raise CandidateParseError("unsupported_media_type")
    if len(parts) == 2 and not re.fullmatch(r'\s*charset\s*=\s*"?utf-8"?\s*', parts[1], re.I):
        raise CandidateParseError("unsupported_charset")
    return media_type


def parse_candidate_document(
    body: bytes, *, content_type: str, capture_kind: str, complete: bool,
) -> ParsedCandidateDocument:
    """Parse only a transport-verified full capture; no storage/use authority."""
    if capture_kind != "full" or complete is not True:
        raise CandidateParseError("incomplete_capture")
    if type(body) is not bytes or not body or len(body) > MAX_BODY_BYTES:
        raise CandidateParseError("body_limit")
    media_type = _media_type(content_type)
    try:
        text = body.decode("utf-8-sig", errors="strict")
    except UnicodeError:
        raise CandidateParseError("invalid_encoding") from None
    if ("\ufffd" in text or "\x00" in text
            or any(ord(char) < 32 and char not in "\n\r\t" for char in text)):
        raise CandidateParseError("invalid_text")
    if media_type != "text/html" and _MARKUP.search(text):
        raise CandidateParseError("media_type_mismatch")
    output = _Fragments()
    if media_type == "text/html":
        if text.rstrip().endswith("<") or re.search(r"<[/!a-zA-Z][^>]*$", text):
            raise CandidateParseError("incomplete_markup")
        parser = _CandidateHTMLParser(output)
        parser.feed(text)
        parser.finish()
    else:
        _parse_lines(text, output, markdown=media_type == "text/markdown")
    if not output.items:
        raise CandidateParseError("empty_content")
    return ParsedCandidateDocument(media_type, hashlib.sha256(body).hexdigest(), tuple(output.items))
