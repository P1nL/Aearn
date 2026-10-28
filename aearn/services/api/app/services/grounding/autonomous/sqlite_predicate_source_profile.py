"""Closed complete HTML assertions for the native three-capture SQLite profile.

Only selected source assertions are qualified. The independent pinned public
course oracle supplies finite semantic evidence, never whole-page approval.
"""
from __future__ import annotations

import hashlib
from typing import Literal

from .source_assessment_profiles import (
    SQLITE_OFFICIAL_UNCLOSED_FOOTERS, SQLITE_ORDER_PARAGRAPH,
    SQLITE_ORDER_TWO_SENTENCE_PARAGRAPH, SQLITE_URL, SourceAssessmentDenied,
    SourceSpan, _Units,
)
from .source_review_repository import CompleteCapture
from .sqlite_select_automated_review import WHERE_PARAGRAPH

SQLiteCaptureRole = Literal["select", "expression", "corefunc"]
SQLITE_PROFILE = "sqlite-predicate-source-v1"
SQLITE_EXPRESSION_URL = "https://www.sqlite.org/lang_expr.html"
SQLITE_COREFUNC_URL = "https://www.sqlite.org/lang_corefunc.html"
SQLITE_CAPTURE_URLS = {"select": SQLITE_URL, "expression": SQLITE_EXPRESSION_URL,
                       "corefunc": SQLITE_COREFUNC_URL}
SQLITE_ARITHMETIC = (
    "The % operator casts both of its operands to type INTEGER and then computes the remainder "
    "after dividing the left integer by the right integer. The other arithmetic operators perform "
    "integer arithmetic if both operands are integers and no overflow would result, or floating "
    "point arithmetic, per IEEE Standard 754, if either operand is a real value or integer "
    "arithmetic would produce an overflow. Integer divide yields an integer result, truncated toward zero."
)
SQLITE_NULL = "All operators generally evaluate to NULL when any operand is NULL, with specific exceptions as stated below. This is in accordance with the SQL92 standard."
SQLITE_NULL_BOOLEAN = "When paired with NULL: AND evaluates to 0 (false) when the other operand is false; and OR evaluates to 1 (true) when the other operand is true."
SQLITE_BOOLEAN = "To convert the results of an SQL expression to a boolean value, SQLite first casts the result to a NUMERIC value in the same way as a CAST expression. A numeric zero value (integer value 0 or real value 0.0) is considered to be false. A NULL value is still NULL. All other values are considered true."
SQLITE_COALESCE = "The coalesce() function returns a copy of its first non-NULL argument, or NULL if all arguments are NULL. Coalesce() must have at least 2 arguments."
SQLITE_ORDER_KEYS = "Rows are first sorted based on the results of evaluating the left-most expression in the ORDER BY list, then ties are broken by evaluating the second left-most expression and so on. The order in which two rows for which all ORDER BY expressions evaluate to equal values are returned is undefined. Each ORDER BY expression may be optionally followed by one of the keywords ASC (smaller values are returned first) or DESC (larger values are returned first). If neither ASC or DESC are specified, rows are sorted in ascending (smaller values first) order by default."
SQLITE_ORDER_NULLS = 'SQLite considers NULL values to be smaller than any other values for sorting purposes. Hence, NULLs naturally appear at the beginning of an ASC order-by and at the end of a DESC order-by. This can be changed using the "ASC NULLS LAST" or "DESC NULLS FIRST" syntax.'
SQLITE_MULTISET = "One of the ALL or DISTINCT keywords may follow the SELECT keyword in a simple SELECT statement. If the simple SELECT is a SELECT ALL, then the entire set of result rows are returned by the SELECT. If neither ALL or DISTINCT are present, then the behavior is as if ALL were specified. If the simple SELECT is a SELECT DISTINCT, then duplicate rows are removed from the set of result rows before it is returned. For the purposes of detecting duplicate rows, values are compared using the IS DISTINCT FROM operator. Thus two NULL values are considered to be equal. An integer is equal to a floating point number if they represent the same quantity. Text values are compared using an appropriate collation sequence. The usual rules apply for selecting a collation sequence to compare text values. BLOB affinity is used for DISTINCT comparisons, hence no type coercions occur."
SQLITE_ASSERTIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "select": {"claim.where": (WHERE_PARAGRAPH,),
               "claim.order": (SQLITE_ORDER_PARAGRAPH, SQLITE_ORDER_TWO_SENTENCE_PARAGRAPH),
               "claim.order-keys": (SQLITE_ORDER_KEYS,), "claim.order-nulls": (SQLITE_ORDER_NULLS,),
               "claim.multiset": (SQLITE_MULTISET,)},
    "expression": {"claim.arithmetic": (SQLITE_ARITHMETIC,), "claim.null": (SQLITE_NULL,),
                   "claim.null-boolean": (SQLITE_NULL_BOOLEAN,), "claim.boolean": (SQLITE_BOOLEAN,)},
    "corefunc": {"claim.coalesce": (SQLITE_COALESCE,)},
}
EXPRESSION_TAIL = '''<p align="center"><small><i>This page was last updated on 2026-08-14 19:21:30Z </small></i></p>

'''
# This official page has no footer/closing body/html. Pin its complete terminal
# definition instead; a fragment ending after coalesce is never a complete page.
COREFUNC_TAIL = '''  SQLite manages these zeroblobs very efficiently.  Zeroblobs can be used to
  reserve space for a BLOB that is later written using\x20
  <a href="c3ref/blob_open.html">incremental BLOB I/O</a>.
  This SQL function is implemented using the <a href="c3ref/result_blob.html">sqlite3_result_zeroblob()</a>
  routine from the C/C++ interface.
</dd>

</dl>


'''


class _SQLiteUnits(_Units):
    def __init__(self, source: str, role: SQLiteCaptureRole) -> None:
        super().__init__(source, SQLITE_ASSERTIONS[role])
        self.role = role
        self.hidden_depths: list[int] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        style = (attributes.get("style") or "").replace(" ", "").lower()
        hidden = ("hidden" in attributes or attributes.get("aria-hidden") == "true"
                  or "display:none" in style or "visibility:hidden" in style)
        super().handle_starttag(tag, attrs)
        if hidden:
            self.hidden_depths.append(len(self.stack))
        if self.unit is not None and self.hidden_depths:
            self.unit_unsafe = True

    def handle_endtag(self, tag: str) -> None:
        # The captured corefunc page explicitly closes each dd, legally omitting
        # its paragraph end. This exception applies only inside that exact dd.
        if (self.role == "corefunc" and tag == "dd" and "dd" in self.stack
                and self.stack[-1:] == ["p"]):
            self._explicit_unit_end = True
            try:
                super(_Units, self).handle_endtag(tag)
            finally:
                self._explicit_unit_end = False
        else:
            super().handle_endtag(tag)
        self.hidden_depths = [depth for depth in self.hidden_depths if depth <= len(self.stack)]


def analyze_sqlite_capture(capture: CompleteCapture, role: SQLiteCaptureRole) -> tuple[SourceSpan, ...]:
    url = SQLITE_CAPTURE_URLS[role]
    if (type(capture) is not CompleteCapture or capture.lane != "registered"
            or capture.origin != "official" or not 0 < len(capture.body) <= 8_388_608
            or capture.digest != hashlib.sha256(capture.body).hexdigest()
            or capture.revision != capture.digest or capture.final_url != url
            or capture.request_chain != (url,) or capture.scope.subject_id != "route.sql"
            or capture.scope.subject_version != "1.0" or capture.scope.facets != ("queries",)):
        raise SourceAssessmentDenied("SOURCE_PROFILE_DENIED")
    try:
        text = capture.body.decode("utf-8")
    except UnicodeDecodeError:
        raise SourceAssessmentDenied("SOURCE_ASSERTIONS_UNSUPPORTED") from None
    parser = _SQLiteUnits(text, role)
    parser.feed(text)
    parser.close()
    tails = (tuple("</p>" + footer for footer in SQLITE_OFFICIAL_UNCLOSED_FOOTERS)
             if role == "select" else (EXPRESSION_TAIL, EXPRESSION_TAIL.replace("\n", "\r\n"))
             if role == "expression" else (COREFUNC_TAIL, COREFUNC_TAIL.replace("\n", "\r\n")))
    complete = parser.closed_html and not parser.stack
    finite_wrapper = (not parser.closed_html and parser.stack == ["html", "body", "div"]
                      and parser.unit is None and not parser.unit_unsafe and text.endswith(tails))
    if (parser.invalid or parser.html_count != 1 or parser.body_count != 1
            or not parser.approved_units_explicitly_closed or not (complete or finite_wrapper)
            or {span[0] for span in parser.spans} != set(SQLITE_ASSERTIONS[role])
            or len(parser.spans) != len(SQLITE_ASSERTIONS[role])):
        raise SourceAssessmentDenied("SOURCE_ASSERTIONS_UNSUPPORTED")
    result = []
    for unit, start, end in parser.spans:
        lo, hi = len(text[:start].encode()), len(text[:end].encode())
        if not 0 < hi - lo <= 4096:
            raise SourceAssessmentDenied("SOURCE_EXCERPT_BOUND")
        result.append(SourceSpan(unit=unit, start_byte=lo, end_byte=hi,
                                 sha256=hashlib.sha256(capture.body[lo:hi]).hexdigest()))
    return tuple(result)


class _SQLiteAnalysisData:
    """At most three capture-role parses in one caller-owned lexical operation.

    Only exact input bytes/metadata and primitive spans live here, never a current
    finding, receipt, signature, connection or permission. The public analyzer
    above remains the cold validator. Returned DTOs are rebuilt on every use.
    """

    def __init__(self) -> None:
        self._entries: dict[tuple[str, SQLiteCaptureRole], tuple[
            tuple[object, ...], tuple[tuple[str, int, int, str], ...]]] = {}
        self._closed = False

    def close(self) -> None:
        self._entries.clear()
        self._closed = True

    def analyze(self, capture: CompleteCapture, role: SQLiteCaptureRole) -> tuple[SourceSpan, ...]:
        try:
            if (self._closed or type(capture) is not CompleteCapture
                    or type(capture.body) is not bytes or type(capture.scope.facets) is not tuple):
                self.close()
                return analyze_sqlite_capture(capture, role)
            # Snapshot nested metadata and the finite rules, not a mutable DTO or
            # a digest-only assertion supplied by a caller. No body normalization.
            key = (capture.capture_id, capture.lane, capture.body, capture.digest, capture.revision,
                   capture.source_handle, capture.final_url, capture.request_chain,
                   capture.scope.subject_id, capture.scope.subject_version, capture.scope.facets,
                   capture.origin, capture.reading_level, capture.license_id, role,
                   analyze_sqlite_capture, _SQLiteUnits, _Units, _SQLiteUnits.__init__,
                   _SQLiteUnits.feed, _SQLiteUnits.close, _SQLiteUnits.handle_starttag, _SQLiteUnits.handle_endtag,
                   _SQLiteUnits.handle_data, _SQLiteUnits._finish_unit, SQLITE_PROFILE, SQLITE_CAPTURE_URLS[role],
                   tuple((unit, tuple(texts)) for unit, texts in SQLITE_ASSERTIONS[role].items()),
                   SQLITE_OFFICIAL_UNCLOSED_FOOTERS, EXPRESSION_TAIL, COREFUNC_TAIL)
            slot = (str(capture.capture_id), role)
            previous = self._entries.get(slot)
            if previous is not None and previous[0] != key:
                # A changed input cannot revive an earlier successful parse.
                self._entries.clear()
                previous = None
            if previous is None:
                spans = analyze_sqlite_capture(capture, role)
                values = tuple((s.unit, s.start_byte, s.end_byte, s.sha256) for s in spans)
                if len(self._entries) < 3:
                    self._entries[slot] = key, values
            else:
                values = previous[1]
            return tuple(SourceSpan(unit=u, start_byte=lo, end_byte=hi, sha256=h) for u, lo, hi, h in values)
        except BaseException:
            # Even a caller catching a parse failure cannot resume warm DATA.
            self.close()
            raise

def _analyze_sqlite_capture(capture: CompleteCapture, role: SQLiteCaptureRole, *,
                            data: _SQLiteAnalysisData | None = None) -> tuple[SourceSpan, ...]:
    return analyze_sqlite_capture(capture, role) if data is None else data.analyze(capture, role)
