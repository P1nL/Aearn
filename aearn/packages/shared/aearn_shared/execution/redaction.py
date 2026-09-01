"""Small deterministic learner-safe projection for execution result text."""
from __future__ import annotations

import re

_PROTECTED_LINE = re.compile(
    r"(?i)(?:docker|container|image[_ -]?(?:id|digest|reference)|sha256:|error response from daemon|"
    r"hidden(?:[_ -]?test|[_ -]?case)|private(?:[_ -]?(?:test|rubric|payload))|"
    r"solution[_ -]?(?:reference|answer)|reference[_ -]?answer|expected(?:[_ -]?(?:value|input|output))?|"
    r"traceback|stack trace|^\s*at\s+[a-z0-9_.$<>]+|^\s*caused by:|\bfile \"|"
    r"[a-z]:[\\/]|/(?:tmp|var|workspace|work|app|home|opt|etc|usr)(?:/|\b)|```|"
    r"\b(?:def|class|function)\s+[a-z_]|^\s*(?:return|raise|import|from)\b|"
    r"\b(?:command|cmd(?:\.exe)?|powershell|pwsh|bash|sh\s+-c|subprocess)\b|"
    r"(?:api[_ -]?key|authorization|bearer|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|"
    r"password|passwd|credential|database[_ -]?url|redis[_ -]?url)\s*[:=]|"
    r"\bbearer\s+[a-z0-9._~+/=-]{8,}|\bsk-[a-z0-9_-]{8,}|"
    r"-----begin [a-z ]*private key-----|\bAKIA[0-9A-Z]{16}\b|"
    r"\b[a-z0-9][a-z0-9.-]*\.[a-z0-9.-]+(?:/[a-z0-9._-]+)+(?:@sha256:[0-9a-f]{64}|:[a-z0-9._-]+))"
)


def sanitize_execution_text(value: object, *, limit: int) -> str:
    """Drop internal/code-bearing lines and cap what can cross the safe boundary."""

    text = str(value or "").replace("\x00", "")
    safe_lines = [line.strip() for line in text.splitlines() if line.strip() and not _PROTECTED_LINE.search(line)]
    result = "\n".join(safe_lines)
    if len(result) > limit:
        result = result[: max(limit - 1, 0)].rstrip() + ("…" if limit > 0 else "")
    return result


def contains_protected_execution_text(value: object) -> bool:
    """Return whether learner-visible text contains an internal or private marker."""

    text = str(value or "")
    return "\x00" in text or any(_PROTECTED_LINE.search(line) for line in text.splitlines())
