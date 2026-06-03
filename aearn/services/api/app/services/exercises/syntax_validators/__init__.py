from __future__ import annotations

import ast
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


SEMANTIC_VALIDATOR_VERSION = "semantic_validator_v1"


@dataclass(frozen=True, slots=True)
class SemanticValidationReport:
    passed: bool
    failure_code: str | None
    matched_tags: list[str]
    missing_tags: list[str]
    validator_key: str
    validator_version: str

    def as_safe_payload(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "failure_code": self.failure_code,
            "matched_tags": self.matched_tags,
            "missing_tags": self.missing_tags,
            "validator_key": self.validator_key,
            "validator_version": self.validator_version,
        }


def validate_exercise_semantics(
    *,
    candidate_payload: Mapping[str, object],
    knowledge_point: Mapping[str, object],
    runtime_profile: Mapping[str, object],
) -> SemanticValidationReport:
    language = _language_id(runtime_profile)
    validator_key = f"{language or 'unknown'}_semantic_alignment"
    required_tags = _required_validator_tags(language, _string_list(knowledge_point.get("skill_tags_json")))
    if not required_tags:
        return SemanticValidationReport(
            passed=True,
            failure_code=None,
            matched_tags=[],
            missing_tags=[],
            validator_key=validator_key,
            validator_version=SEMANTIC_VALIDATOR_VERSION,
        )

    declared_tags = _declared_candidate_skill_tags(candidate_payload)
    matched: list[str] = []
    missing: list[str] = []
    for tag in required_tags:
        if tag in declared_tags and _tag_matches(tag, language, candidate_payload):
            matched.append(tag)
        else:
            missing.append(tag)

    return SemanticValidationReport(
        passed=not missing,
        failure_code=None if not missing else "missing_required_skill",
        matched_tags=matched,
        missing_tags=missing,
        validator_key=validator_key,
        validator_version=SEMANTIC_VALIDATOR_VERSION,
    )


def _required_validator_tags(language: str, skill_tags: Sequence[str]) -> list[str]:
    normalized = [_normalize_tag(tag) for tag in skill_tags]
    required: list[str] = []
    if language == "python":
        _append_if_present(required, normalized, "list_comprehension")
    elif language == "sql":
        for tag in ("select", "filtering", "sorting", "joins", "aggregation"):
            _append_if_present(required, normalized, tag)
    elif language == "javascript":
        _append_if_present(required, normalized, "functions")
        if "dom_events" in normalized or "dom" in normalized or "event" in normalized:
            required.append("dom_events")
    elif language == "typescript":
        for tag in ("functions", "types"):
            _append_if_present(required, normalized, tag)
    elif language == "html_css":
        for tag in (
            "semantics",
            "accessibility",
            "forms",
            "selectors",
            "box_model",
            "typography",
            "state",
            "layout",
            "positioning",
            "responsive",
        ):
            _append_if_present(required, normalized, tag)
    elif language in {"java", "go", "csharp"}:
        for tag in ("functions", "types", "control_flow"):
            _append_if_present(required, normalized, tag)
    return required


def _append_if_present(target: list[str], tags: Sequence[str], tag: str) -> None:
    if tag in tags and tag not in target:
        target.append(tag)


def _tag_matches(tag: str, language: str, candidate_payload: Mapping[str, object]) -> bool:
    code = _candidate_code(candidate_payload)
    if language == "python" and tag == "list_comprehension":
        return _python_has_list_comprehension(code)
    if language == "sql":
        return _sql_tag_matches(tag, code)
    if language == "javascript":
        return _javascript_tag_matches(tag, code)
    if language == "typescript":
        return _typescript_tag_matches(tag, code)
    if language == "html_css":
        return _html_css_tag_matches(tag, code)
    if language == "java":
        return _java_tag_matches(tag, code)
    if language == "go":
        return _go_tag_matches(tag, code)
    if language == "csharp":
        return _csharp_tag_matches(tag, code)
    return True


def _python_has_list_comprehension(code: str) -> bool:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    return any(isinstance(node, ast.ListComp) for node in ast.walk(tree))


def _sql_tag_matches(tag: str, code: str) -> bool:
    tokens = _sql_tokens(code)
    token_set = set(tokens)
    if tag == "select":
        return "select" in token_set and "from" in token_set
    if tag == "filtering":
        return "where" in token_set
    if tag == "sorting":
        return _contains_phrase(tokens, ("order", "by"))
    if tag == "joins":
        return "join" in token_set
    if tag == "aggregation":
        aggregate_functions = {"count", "sum", "avg", "min", "max"}
        return bool(token_set & aggregate_functions) and _contains_phrase(tokens, ("group", "by"))
    return True


def _javascript_tag_matches(tag: str, code: str) -> bool:
    if tag == "functions":
        return _has_function_marker(code)
    if tag == "dom_events":
        lowered = code.lower()
        return "addeventlistener" in lowered or re.search(r"\.on[a-z]+\s*=", lowered) is not None
    return True


def _typescript_tag_matches(tag: str, code: str) -> bool:
    if tag == "functions":
        return _has_function_marker(code)
    if tag == "types":
        return re.search(r":\s*[A-Za-z][A-Za-z0-9_<>, \[\]\|]*", code) is not None or re.search(r"\b(type|interface)\s+\w+", code) is not None
    return True


def _html_css_tag_matches(tag: str, code: str) -> bool:
    lowered = code.lower()
    if tag == "semantics":
        return any(marker in lowered for marker in ("<main", "<section", "<article", "<header", "<footer", "<nav", "<h1"))
    if tag == "accessibility":
        return any(marker in lowered for marker in ("<label", "aria-", " role=", "<button", " alt="))
    if tag == "forms":
        return any(marker in lowered for marker in ("<form", "<input", "<textarea", "<select", "<label"))
    if tag == "selectors":
        return re.search(r"(^|[{}])\s*(\.|#|[a-z][\w-]*(\.|#|\[|:))[\w\-:#.\[\]=>\"' ]*\s*\{", lowered) is not None
    if tag == "box_model":
        return any(marker in lowered for marker in ("margin", "padding", "border", "box-sizing", "width", "height"))
    if tag == "typography":
        return any(marker in lowered for marker in ("font-size", "font-weight", "line-height", "font-family"))
    if tag == "state":
        return any(marker in lowered for marker in (".active", ":hover", ":focus", "[aria-"))
    if tag == "layout":
        return any(marker in lowered for marker in ("display: flex", "display:flex", "display: grid", "display:grid", "grid-template"))
    if tag == "positioning":
        return "position:" in lowered or any(marker in lowered for marker in ("top:", "right:", "bottom:", "left:", "z-index"))
    if tag == "responsive":
        return "@media" in lowered or any(marker in lowered for marker in ("clamp(", "minmax(", "max-width", "min-width"))
    return True


def _java_tag_matches(tag: str, code: str) -> bool:
    if tag == "functions":
        return re.search(r"\b(public|private|protected)?\s*(static\s+)?[\w<>\[\]]+\s+\w+\s*\(", code) is not None
    if tag == "types":
        return re.search(r"\b(class|interface|enum|int|long|double|float|boolean|String|void)\b", code) is not None
    if tag == "control_flow":
        return _has_control_flow_marker(code)
    return True


def _go_tag_matches(tag: str, code: str) -> bool:
    if tag == "functions":
        return re.search(r"\bfunc\s+\w+\s*\(", code) is not None
    if tag == "types":
        return re.search(r"\bfunc\s+\w+\s*\([^)]*\b\w+\s+\w+", code) is not None or re.search(r"\)\s+\*?\w+", code) is not None or re.search(r"\btype\s+\w+", code) is not None
    if tag == "control_flow":
        return _has_control_flow_marker(code)
    return True


def _csharp_tag_matches(tag: str, code: str) -> bool:
    if tag == "functions":
        return re.search(r"\b(public|private|internal)?\s*(static\s+)?[\w<>\[\]]+\s+\w+\s*\(", code) is not None
    if tag == "types":
        return re.search(r"\b(class|interface|enum|int|string|bool|double|decimal|void|var)\b", code) is not None
    if tag == "control_flow":
        return _has_control_flow_marker(code)
    return True


def _has_function_marker(code: str) -> bool:
    return re.search(r"\bfunction\s+\w+", code) is not None or "=>" in code


def _has_control_flow_marker(code: str) -> bool:
    return re.search(r"\b(if|else|for|while|switch|case)\b", code) is not None


def _candidate_code(candidate_payload: Mapping[str, object]) -> str:
    parts: list[str] = []
    for key in ("starter_code", "solution_reference"):
        value = candidate_payload.get(key)
        if isinstance(value, str):
            parts.append(value)
    return "\n".join(parts)


def _sql_tokens(query: str) -> list[str]:
    cleaned = _remove_sql_comments_and_literals(query)
    return [match.group(0).lower() for match in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", cleaned)]


def _remove_sql_comments_and_literals(query: str) -> str:
    chars: list[str] = []
    state = "normal"
    index = 0
    while index < len(query):
        char = query[index]
        next_char = query[index + 1] if index + 1 < len(query) else ""
        if state == "normal":
            if char == "'":
                state = "single"
                chars.append(" ")
            elif char == '"':
                state = "double"
                chars.append(" ")
            elif char == "-" and next_char == "-":
                state = "line_comment"
                chars.append(" ")
                index += 1
            elif char == "/" and next_char == "*":
                state = "block_comment"
                chars.append(" ")
                index += 1
            else:
                chars.append(char)
        elif state == "single":
            chars.append(" ")
            if char == "'" and next_char == "'":
                index += 1
                chars.append(" ")
            elif char == "'":
                state = "normal"
        elif state == "double":
            chars.append(" ")
            if char == '"' and next_char == '"':
                index += 1
                chars.append(" ")
            elif char == '"':
                state = "normal"
        elif state == "line_comment":
            chars.append(" ")
            if char in {"\n", "\r"}:
                state = "normal"
        elif state == "block_comment":
            chars.append(" ")
            if char == "*" and next_char == "/":
                state = "normal"
                index += 1
                chars.append(" ")
        index += 1
    return "".join(chars)


def _contains_phrase(tokens: Sequence[str], phrase: Sequence[str]) -> bool:
    if not phrase:
        return False
    for index in range(0, len(tokens) - len(phrase) + 1):
        if tuple(tokens[index : index + len(phrase)]) == tuple(phrase):
            return True
    return False


def _language_id(runtime_profile: Mapping[str, object]) -> str:
    language = str(runtime_profile.get("language") or "").strip().lower()
    if language in {"html", "css"}:
        return "html_css"
    return language


def _string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return []
    return [_normalize_tag(str(item)) for item in value if str(item).strip()]


def _declared_candidate_skill_tags(candidate_payload: Mapping[str, object]) -> set[str]:
    metadata = candidate_payload.get("metadata_json")
    if not isinstance(metadata, Mapping):
        return set()
    declared: set[str] = set(_string_list(metadata.get("target_skill_tags")))
    alignment = metadata.get("model_alignment")
    if isinstance(alignment, Mapping):
        declared.update(_string_list(alignment.get("target_skill_tags")))
    return declared


def _normalize_tag(value: str) -> str:
    return value.strip().lower().replace("-", "_")
