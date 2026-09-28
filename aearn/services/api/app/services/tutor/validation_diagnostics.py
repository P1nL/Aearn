"""Readable diagnostics derived only from the server's schema, never rejected values."""
from __future__ import annotations

import re
from functools import lru_cache

from pydantic import BaseModel, ValidationError

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
        # Keep the union root: visiting its branches must not overwrite anyOf
        # with whichever type happened to be visited last.
        if previous is None or "anyOf" not in previous[1]:
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
    # Reuse the actual pure planning domain schemas, not a copied limits table.
    from app.services.learning.plan_drafting import CompactPlanModule, CompactPlanProfile
    domain_models: tuple[tuple[str, type[BaseModel]], ...] = (
        ("profile_json", CompactPlanProfile),
        *((f"module_{index}", CompactPlanModule) for index in range(1, 9)),
    )
    for key, model in domain_models:
        domain_schema = model.model_json_schema()
        definitions.update(domain_schema.get("$defs", {}))
        prefix = ("action", "arguments", key)
        visit(domain_schema, prefix, prefix, 0)
    return fields


def plan_domain_validation_issues(exc: ValidationError, *, argument_key: str) -> tuple[TutorDecisionValidationIssue, ...]:
    """Only known model fields and shape counts survive a domain validation error."""
    prefix = ("action", "arguments", argument_key)
    issues = []
    for error in exc.errors(include_url=False, include_context=False)[:8]:
        location = (*prefix, *error["loc"])
        indexed = tuple("*" if type(part) is int and 0 <= part <= 8 else str(part) for part in location)
        # Never echo extra-key names or arbitrary values in validation messages.
        path = ".".join(map(str, location)) if indexed in _known_fields() else ".".join(prefix)
        value = error.get("input")
        observed = {str: "string", list: "array", dict: "object", int: "integer",
                    float: "number", bool: "boolean", type(None): "null"}.get(type(value))
        issues.append(TutorDecisionValidationIssue(
            path=path, category="plan_domain_invalid", argument_key=argument_key,
            observed_type=observed, string_length=len(value) if isinstance(value, str) else None,
            list_count=len(value) if isinstance(value, list) else None,
        ))
    return tuple(issues)


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
    safe_argument_key = (
        issue.argument_key if issue.argument_key == "profile_json"
        or (isinstance(issue.argument_key, str) and re.fullmatch(r"module_[1-8]", issue.argument_key))
        else None
    )
    if safe_argument_key is not None:
        result["argument_key"] = safe_argument_key
    if issue.observed_type in {"string", "integer", "number", "boolean", "array", "object", "null"}:
        result["observed_type"] = issue.observed_type
    if issue.string_length is not None:
        result["string_length"] = issue.string_length
    if issue.serialized_length is not None:
        result["serialized_length"] = issue.serialized_length
    if issue.list_count is not None:
        result["list_count"] = issue.list_count
    if types := tuple(
        dict.fromkeys(branch["type"] for branch in node.get("anyOf", [])
                      if isinstance(branch, dict) and isinstance(branch.get("type"), str))
    ):
        result["expected_types"] = types
    if issue.category == "plan_domain_invalid":
        if isinstance(node.get("type"), str):
            result["expected_type"] = node["type"]
        limits = ", ".join(f"{key}={node[key]}" for key in (
            "minLength", "maxLength", "minItems", "maxItems", "minimum", "maximum",
        ) if key in node)
        result["expected_rule"] = (
            "Repair this field using the existing plan domain type and required shape; omit unknown fields. "
            + (f"Domain bounds: {limits}. " if limits else "")
            + "Preserve goals and prerequisites; put longer availability explanations in message.text."
        )
    elif issue.category == "plan_json_invalid":
        result["expected_rule"] = "This plan argument must encode a valid JSON object, not an array or scalar."
    elif rule := _TEACHING_SEMANTIC_REPAIR_GUIDANCE.get(issue.category):
        result["expected_rule"] = rule
    elif issue.category == "invalid_literal":
        result["expected_rule"] = "Use an exact value from expected_values; synonyms are not valid."
    elif issue.category == "missing":
        result["expected_rule"] = "This schema field is required."
    elif safe_argument_key is not None and issue.category == "invalid_value" and issue.observed_type == "string":
        raw_limit = 1024 if issue.argument_raw_limit == 1024 else 360
        result["expected_rule"] = (
            f"Plan draft profile_json/module_N strings may contain at most {raw_limit} raw characters "
            "before outer JSON string escaping."
        )
    elif isinstance(node.get("type"), str) and "expected_types" not in result:
        result["expected_type"] = node["type"]
    return result
