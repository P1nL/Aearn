"""Readable diagnostics derived only from the server's schema, never rejected values."""
from __future__ import annotations

import re
from functools import lru_cache

from app.core.safe_diagnostics import safe_diagnostic_identifier
from app.services.tutor.decision_protocol import (
    TutorDecisionValidationIssue,
    _TEACHING_SEMANTIC_REPAIR_GUIDANCE,
    tutor_provider_output_schema,
)


@lru_cache(maxsize=1)
def _known_fields() -> dict[tuple[str, ...], tuple[tuple[str, ...], dict]]:
    """Index both JSON paths and Pydantic's known discriminated-union paths."""
    schema = tutor_provider_output_schema()
    raw_definitions = schema.get("$defs", {})
    definitions = raw_definitions if isinstance(raw_definitions, dict) else {}
    fields: dict[tuple[str, ...], tuple[tuple[str, ...], dict]] = {}

    def visit(node: dict, path: tuple[str, ...], canonical: tuple[str, ...], depth: int) -> None:
        if depth > 24:
            return
        if "$ref" in node:
            name = node["$ref"].removeprefix("#/$defs/")
            visit(definitions.get(name, {}), path, canonical, depth + 1)
            return
        merged = dict(node)
        if previous := fields.get(path):
            old = previous[1]
            values = [*old.get("enum", [old["const"]] if "const" in old else []),
                      *node.get("enum", [node["const"]] if "const" in node else [])]
            if values:
                merged.pop("const", None)
                merged["enum"] = list(dict.fromkeys(values))
        fields[path] = (canonical, merged)
        for tag, reference in node.get("discriminator", {}).get("mapping", {}).items():
            visit({"$ref": reference}, (*path, tag), canonical, depth + 1)
        for key in ("oneOf", "anyOf"):
            for branch in node.get(key, []):
                if branch.get("type") == "null":
                    continue
                visit(branch, path, canonical, depth + 1)
        for name, child in node.get("properties", {}).items():
            visit(child, (*path, name), (*canonical, name), depth + 1)
        if isinstance(node.get("items"), dict):
            visit(node["items"], (*path, "*"), (*canonical, "*"), depth + 1)

    visit(dict(schema), (), (), 0)
    return fields


def validation_log_fields(issue: TutorDecisionValidationIssue) -> dict[str, object]:
    try:
        return _validation_log_fields(issue)
    except Exception:
        # Diagnostics must never interrupt rejection handling or consume a retry.
        return {"field_path": safe_diagnostic_identifier(issue.path, trusted=False)}


def _validation_log_fields(issue: TutorDecisionValidationIssue) -> dict[str, object]:
    """Unknown keys stay hashed; enum values/rule text come only from local code."""
    parts = issue.path.split(".")
    if "*" in parts:
        # A literal provider-supplied '*' is not a schema array-index placeholder.
        return {"field_path": safe_diagnostic_identifier(issue.path, trusted=False)}
    path = tuple("*" if re.fullmatch(r"[0-9]{1,4}", part) else part for part in parts)
    known = _known_fields().get(path)
    if known is None:
        return {"field_path": safe_diagnostic_identifier(issue.path, trusted=False)}
    canonical, node = known
    indices = iter(part for part in parts if re.fullmatch(r"[0-9]{1,4}", part))
    rendered = ""
    for part in canonical:
        rendered += f"[{next(indices)}]" if part == "*" else ("." if rendered else "") + part
    result: dict[str, object] = {"field_path": rendered or "root"}
    expected = node.get("enum", [node["const"]] if "const" in node else [])
    if expected:
        result["expected_values"] = tuple(str(value) for value in expected)
    if rule := _TEACHING_SEMANTIC_REPAIR_GUIDANCE.get(issue.category):
        result["expected_rule"] = rule
    elif issue.category == "invalid_literal":
        result["expected_rule"] = "Use an exact value from expected_values; synonyms are not valid."
    elif issue.category == "missing":
        result["expected_rule"] = "This schema field is required."
    elif isinstance(node.get("type"), str):
        result["expected_type"] = node["type"]
    return result
