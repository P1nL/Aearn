"""Small deterministic learner-safe projection for execution result text."""
from __future__ import annotations

import re


_PROTECTED_LINE = re.compile(
    r"(?i)(?:docker|container|sha256:|error response from daemon|hidden(?:[_ -]?test|[_ -]?case)|"
    r"solution[_ -]?(?:reference|answer)|expected(?:[_ -]?value)?|traceback|stack trace|"
    r"\bfile \"|[a-z]:[\\/]|/(?:tmp|var|workspace|work|app|home)/|```|"
    r"\b(?:def|class|function)\s+[a-z_]|^\s*(?:return|raise|import|from)\b|"
    r"\b[a-z0-9][a-z0-9.-]*\.[a-z0-9.-]+(?:/[a-z0-9._-]+)+(?:@sha256:[0-9a-f]{64}|:[a-z0-9._-]+))"
)


def sanitize_execution_text(value: object, *, limit: int) -> str:
    """Drop internal/code-bearing lines and cap what can cross the safe boundary."""

    text = str(value or "").replace("\x00", "")
    safe_lines = [line.strip() for line in text.splitlines() if line.strip() and not _PROTECTED_LINE.search(line)]
    result = "\n".join(safe_lines)
    if len(result) > limit:
        result = result[:limit].rstrip() + "…"
    return result
