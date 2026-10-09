"""Finite visible tutorial code groups, not a whole-page quality endorsement.

No network, model or host execution. The unsupported declarations generalization
and every other unlisted teaching group are excluded from this profile.

The exact source assertion strings below are from Learn X in Y Minutes: Python,
by Louie Dinh and the contributors listed in AUTHORS, CC BY-SA 3.0. Their source
and license URLs and unchanged-excerpt attribution are retained in every review.
"""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
import re
from typing import Any, Literal

from aearn_shared.execution import ExecutionAction, SandboxInputV1
from pydantic import model_validator

from app.services.learning.item_bank.contracts import canonical_hash

from .contracts import FrozenContract
from .source_assessment_profiles import SourceSpan, _Units
from .source_review_repository import CompleteCapture
from .sqlite_select_automated_review import SKIP, UNSAFE_CONTEXT

URL = "https://learnxinyminutes.com/python/"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/3.0/deed.en_US"
PROBE = "public_python_teaching_oracle"
USAGES: tuple[Literal["main_teaching"], ...] = ("main_teaching",)
AUTHORS = ("Louie Dinh", "Steven Basart", "Andre Polykanine", "Zachary Ferguson", "evuez",
           "Rommel Martinez", "Roberto Fernandez Diaz", "caminsha", "Stanislav Modrak", "John Paul Wohlscheid")
GROUPS = {
    "teaching.print": '# Python has a print function\nprint("I\'m Python. Nice to meet you!")  # => I\'m Python. Nice to meet you!',
    "teaching.print-end": '# By default the print function also prints out a newline at the end.\n# Use the optional argument end to change the end string.\nprint("Hello, World", end="!")  # => Hello, World!',
    "teaching.unpack-swap": "# You can unpack tuples (or lists) into variables\na, b, c = (1, 2, 3)  # a is now 1, b is now 2 and c is now 3\n# You can also do extended unpacking\na, *b, c = (1, 2, 3, 4)  # a is now 1, b is now [2, 3] and c is now 4\n# Tuples are created by default if you leave out the parentheses\nd, e, f = 4, 5, 6  # tuple 4, 5, 6 is unpacked into variables d, e and f\n# respectively such that d = 4, e = 5 and f = 6\n# Now look how easy it is to swap two values\ne, d = d, e  # d is now 5 and e is now 4",
}


class TeachingReviewDenied(ValueError):
    """Bounded refusal; no body, secret or raw terminal."""


class TeachingAttribution(FrozenContract):
    title: Literal["Learn X in Y Minutes: Python"] = "Learn X in Y Minutes: Python"
    source_url: Literal["https://learnxinyminutes.com/python/"] = "https://learnxinyminutes.com/python/"
    license_id: Literal["cc-by-sa-3.0"] = "cc-by-sa-3.0"
    license_url: Literal["https://creativecommons.org/licenses/by-sa/3.0/deed.en_US"] = "https://creativecommons.org/licenses/by-sa/3.0/deed.en_US"
    authors: tuple[str, ...] = AUTHORS
    changes: Literal["Unmodified excerpts; source syntax-highlighting markup retained."] = "Unmodified excerpts; source syntax-highlighting markup retained."

    @model_validator(mode="after")
    def exact(self) -> TeachingAttribution:
        if self.authors != AUTHORS:
            raise ValueError("teaching attribution mismatch")
        return self


class _VisibleCode(_Units):
    def __init__(self, text: str) -> None:
        super().__init__(text, {})
        self.code_start: int | None = None
        self.code_ranges: list[tuple[int, int]] = []
        self.license_seen = False
        self.footer_text: list[str] = []
        self.attributes: dict[int, list[tuple[str, str | None]]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "pre":
            hidden = any(key in ("hidden", "inert", "style") or key.startswith("on")
                         or key == "aria-hidden" and value != "false"
                         or key == "class" and value not in ("container", "highlight")
                         for depth, pairs in self.attributes.items() if depth <= len(self.stack)
                         for key, value in pairs)
            if (self.code_start is not None or attrs != [("lang", "python")]
                    or hidden or any(t in self.stack for t in SKIP | UNSAFE_CONTEXT) or "body" not in self.stack):
                self.invalid = True
            self.code_start = self._offset() + len(self.get_starttag_text() or "")
        if tag == "a" and "footer" in self.stack:
            values = dict(attrs)
            if values.get("rel") == "license" and values.get("href") == LICENSE_URL:
                self.license_seen = True
        super().handle_starttag(tag, attrs)
        if self.stack and self.stack[-1] == tag:
            self.attributes[len(self.stack)] = attrs

    def handle_endtag(self, tag: str) -> None:
        if tag == "pre":
            if self.code_start is None or not self.stack or self.stack[-1] != "pre":
                self.invalid = True
            else:
                self.code_ranges.append((self.code_start, self._offset()))
            self.code_start = None
        super().handle_endtag(tag)
        self.attributes = {depth: attrs for depth, attrs in self.attributes.items() if depth <= len(self.stack)}

    def handle_data(self, data: str) -> None:
        if "footer" in self.stack and not any(t in self.stack for t in SKIP):
            self.footer_text.append(data)
        super().handle_data(data)


class _CodeGroup(HTMLParser):
    """Only source syntax-highlight spans, never hidden/style/event/link markup."""
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.invalid = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if (tag != "span" or len(attrs) != 1 or attrs[0][0] != "class"
                or re.fullmatch(r"[a-z][a-z0-9]{0,7}", attrs[0][1] or "") is None or self.depth):
            self.invalid = True
        self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag != "span" or self.depth != 1:
            self.invalid = True
        self.depth -= 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.invalid = True

    def handle_comment(self, data: str) -> None:
        self.invalid = True

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def analyze_teaching(capture: CompleteCapture) -> tuple[SourceSpan, ...]:
    if (type(capture) is not CompleteCapture or capture.lane != "registered"
            or capture.final_url != URL or capture.request_chain != (URL,)
            or capture.origin != "tutorial" or capture.license_id != "cc-by-sa-3.0"
            or capture.reading_level != "beginner" or capture.scope.subject_id != "route.python"
            or capture.scope.subject_version != "1.0" or capture.scope.facets != ("fundamentals",)
            or not 0 < len(capture.body) <= 4_194_304
            or capture.digest != hashlib.sha256(capture.body).hexdigest() or capture.revision != capture.digest):
        raise TeachingReviewDenied("TEACHING_CAPTURE_DENIED")
    text = capture.body.decode("utf-8")
    parser = _VisibleCode(text)
    parser.feed(text)
    parser.close()
    if (parser.invalid or parser.stack or not parser.closed_html or parser.html_count != 1
            or parser.body_count != 1 or len(parser.code_ranges) != 1 or not parser.license_seen
            or any(author not in " ".join(parser.footer_text) for author in AUTHORS)):
        raise TeachingReviewDenied("TEACHING_DOCUMENT_STRUCTURE_DENIED")
    first, last = parser.code_ranges[0]
    selected: dict[str, SourceSpan] = {}
    # Entire source-authored blank-line groups, never a true-looking sub-sentence.
    for match in re.finditer(r"(?:[^\n]|\n(?!\s*\n))+", text[first:last]):
        raw = match.group().strip("\r\n")
        group = _CodeGroup()
        group.feed(raw)
        group.close()
        plain = "".join(group.parts).strip("\r\n")
        unit = next((name for name, expected in GROUPS.items() if plain == expected), None)
        if unit is None:
            continue
        if group.invalid or group.depth or unit in selected:
            raise TeachingReviewDenied("TEACHING_GROUP_DENIED")
        start = first + match.start() + len(match.group()) - len(match.group().lstrip("\r\n"))
        lo, hi = len(text[:start].encode()), len(text[:start + len(raw)].encode())
        if not 0 < hi - lo <= 8000:
            raise TeachingReviewDenied("TEACHING_GROUP_DENIED")
        selected[unit] = SourceSpan(unit=unit,start_byte=lo,end_byte=hi,sha256=hashlib.sha256(capture.body[lo:hi]).hexdigest())
    if set(selected) != set(GROUPS):
        raise TeachingReviewDenied("TEACHING_ASSERTIONS_UNSUPPORTED")
    return tuple(sorted(selected.values(), key=lambda s: s.start_byte))


def teaching_request() -> tuple[SandboxInputV1, dict[str, Any]]:
    code = ('print("I\'m Python. Nice to meet you!")\nprint("Hello, World", end="!")\n'
            'a,b,c=(1,2,3)\nprint(a,b,c)\na,*b,c=(1,2,3,4)\nprint(a,b,c)\n'
            'd,e,f=4,5,6\nprint(d,e,f)\ne,d=d,e\nprint(d,e,f)\n')
    cases = [{"id": "teaching_source", "case_type": "visible"}]
    expected = {"cases": [{"id": "teaching_source", "status": "success", "code": "python_terminal",
        "stdout": "I'm Python. Nice to meet you!\nHello, World!1 2 3\n1 [2, 3] 4\n4 5 6\n5 4 6\n"}]}
    return SandboxInputV1(runtime_id="python-stdout-v1",action=ExecutionAction.TEST,submission=code,
        visible_test_bundle_json=json.dumps(cases,separators=(",",":")),hidden_test_bundle_json="[]",
        source_reference_hash=canonical_hash({"groups":GROUPS,"code":code}),test_reference_hash=canonical_hash(cases)), expected
