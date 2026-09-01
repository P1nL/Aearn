"""Pure deterministic validation receipts for Learning Item Bank sources."""
from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import unquote

from app.services.learning.item_bank.contracts import (
    LearningItemCodeContentV1,
    LearningItemCodePrivateV1,
    LearningItemDemoContentV1,
    LearningItemDemoPrivateV1,
    LearningItemKnowledgeCheckContentV1,
    LearningItemKnowledgeCheckPrivateV1,
    LearningItemKind,
    LearningItemModelReviewContentV1,
    LearningItemModelReviewPrivateV1,
    LearningItemSourceV1,
    LearningItemSqlContentV1,
    LearningItemSqlPrivateV1,
    LearningItemValidationCheckType,
    LearningItemValidationCheckV1,
    LearningItemValidationReceiptV1,
    canonical_hash,
    learning_item_handle,
    normalize_answer,
)
from app.services.learning.item_bank.practice_adapter import build_exercise_authority
from app.services.learning.practice.model_review_contracts import (
    MODEL_REVIEW_SCORE_POLICY_VERSION,
    ModelReviewAssistanceKind,
)
from app.services.learning.practice.model_review_quality import (
    candidate_hash,
    require_model_review_quality,
)
from app.services.learning.practice.model_review_scoring import evaluate_model_code_review
from app.services.learning.practice.quality import require_exercise_quality
from app.services.runners.browser_preview_runner import execute_browser_preview_with_tests
from app.services.runners.sql_query_runner import execute_sql_query_with_tests


_STATUS = Literal["passed", "failed", "not_applicable"]
_PROTECTED_PUBLIC_MARKERS = (
    "private_test",
    "hidden_test",
    "reference_answer",
    "standard_answer",
    "standard_query",
    "accepted_answers",
    "answer_explanation_markdown",
    "expected_findings",
    "matcher_tokens",
    "reachability_proof",
    "setup_sql",
    "provider_body",
    "reasoning_content",
    "docker.sock",
    "container_id",
    "image_reference",
    "authorization:",
    "api_key",
)
_SQL_UNSAFE = frozenset(
    {
        "alter", "attach", "begin", "commit", "create", "delete", "detach",
        "drop", "insert", "load_extension", "pragma", "reindex", "release",
        "replace", "rollback", "savepoint", "transaction", "update", "vacuum",
    }
)
_TOKEN = re.compile(r"[a-z0-9_.$:-]+|[\u4e00-\u9fff]{2,}", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class _Outcome:
    status: _STATUS
    safe_code: str | None
    evidence: Mapping[str, object]


def validate_learning_item(source: LearningItemSourceV1) -> LearningItemValidationReceiptV1:
    """Return a deterministic, learner-safe receipt without durable side effects."""

    content_hash = source.content_hash
    handle = learning_item_handle(source.public.item_key, source.public.version, content_hash)
    outcomes = (
        (LearningItemValidationCheckType.SCHEMA, _ok({"source_hash": source.source_hash})),
        (LearningItemValidationCheckType.SOURCE_REFERENCES, _source_references(source)),
        (LearningItemValidationCheckType.DIFFICULTY_PROFILE, _difficulty(source)),
        (LearningItemValidationCheckType.PUBLIC_PRIVATE_BOUNDARY, _public_private(source)),
        (LearningItemValidationCheckType.MARKDOWN_SAFETY, _markdown(source)),
        (LearningItemValidationCheckType.HINT_LEAKAGE, _hints(source)),
        (LearningItemValidationCheckType.PRACTICE_CONTRACT, _practice(source)),
        (LearningItemValidationCheckType.STANDARD_ANSWER, _standard_answer(source)),
        (LearningItemValidationCheckType.STARTER_NOT_PASSING, _starter(source)),
        (LearningItemValidationCheckType.RUNTIME_OR_EVENT, _runtime_or_event(source)),
        (LearningItemValidationCheckType.SCORER, _scorer(source)),
    )
    return LearningItemValidationReceiptV1(
        item_handle=handle,
        content_hash=content_hash,
        checks=tuple(
            LearningItemValidationCheckV1(
                check_type=check_type,
                status=outcome.status,
                safe_code=outcome.safe_code,
                proof_hash=canonical_hash(
                    {
                        "content_hash": content_hash,
                        "check_type": check_type.value,
                        "status": outcome.status,
                        "safe_code": outcome.safe_code,
                        "evidence": dict(outcome.evidence),
                    }
                ),
            )
            for check_type, outcome in outcomes
        ),
    )


def _ok(evidence: Mapping[str, object] | None = None) -> _Outcome:
    return _Outcome("passed", None, evidence or {})


def _bad(code: str, evidence: Mapping[str, object] | None = None) -> _Outcome:
    return _Outcome("failed", code, evidence or {})


def _na(kind: LearningItemKind) -> _Outcome:
    return _Outcome("not_applicable", None, {"kind": kind.value})


def _source_references(source: LearningItemSourceV1) -> _Outcome:
    refs = source.blueprint.source_references
    if any(
        item.content_hash == "0" * 64
        or ".." in item.locator
        or "\x00" in item.locator
        or "<" in item.locator
        or ">" in item.locator
        for item in refs
    ):
        return _bad("source_reference_invalid", {"count": len(refs)})
    return _ok({"count": len(refs), "references_hash": canonical_hash([item.model_dump(mode="json") for item in refs])})


def _difficulty(source: LearningItemSourceV1) -> _Outcome:
    profile = source.blueprint.difficulty_profile
    if profile.computed_base is not profile.base or source.public.difficulty is not profile.base:
        return _bad("difficulty_profile_mismatch", {"declared": profile.base.value, "computed": profile.computed_base.value})
    return _ok({"base": profile.base.value, "profile_hash": canonical_hash(profile.model_dump(mode="json"))})


def _public_private(source: LearningItemSourceV1) -> _Outcome:
    public_text = str(source.public.model_dump(mode="json")).casefold()
    if any(marker in public_text for marker in _PROTECTED_PUBLIC_MARKERS):
        return _bad("public_private_boundary_violation")
    return _ok({"public_hash": source.public.public_hash, "private_hash": source.private.private_hash})


def _markdown(source: LearningItemSourceV1) -> _Outcome:
    values = [source.public.instruction_markdown, *(hint.markdown for hint in source.public.hints)]
    content = source.public.content
    private = source.private.content
    if isinstance(content, LearningItemSqlContentV1):
        values.append(content.schema_markdown)
    elif isinstance(content, LearningItemKnowledgeCheckContentV1):
        values.append(content.prompt_markdown)
    elif isinstance(content, LearningItemModelReviewContentV1):
        values.extend((*content.prompt.requirements, content.prompt.learner_instruction))
    if isinstance(private, LearningItemKnowledgeCheckPrivateV1):
        values.append(private.answer_explanation_markdown)
    if any(_unsafe_markdown(value) for value in values):
        return _bad("markdown_unsafe", {"field_count": len(values)})
    return _ok({"field_count": len(values), "markdown_hash": canonical_hash(values)})


def _unsafe_markdown(value: str) -> bool:
    prose = _without_code(value)
    decoded = html.unescape(prose)
    for _ in range(2):
        decoded = unquote(decoded)
    compact = re.sub(r"[\s\x00-\x20\u200b-\u200f\ufeff]+", "", decoded).casefold()
    lowered = decoded.casefold()
    return bool(
        re.search(r"<!--|<\s*/?\s*[a-z][^>]*>", decoded, flags=re.IGNORECASE)
        or any(scheme in compact for scheme in ("javascript:", "vbscript:", "data:text/html", "file:"))
        or re.search(r"\bon[a-z]+\s*=|\bstyle\s*=", lowered)
        or "\x00" in value
    )


def _without_code(value: str) -> str:
    lines: list[str] = []
    fence: str | None = None
    for line in value.splitlines():
        stripped = line.lstrip()
        marker = "```" if stripped.startswith("```") else "~~~" if stripped.startswith("~~~") else None
        if marker is not None:
            fence = None if fence == marker else marker if fence is None else fence
            continue
        if fence is None:
            lines.append(line)
    return re.sub(r"`[^`]*`", "", "\n".join(lines))


def _hints(source: LearningItemSourceV1) -> _Outcome:
    if not source.public.hints:
        return _na(source.public.kind)
    hints = "\n".join(item.markdown for item in source.public.hints)
    private = source.private.content
    public = source.public.content
    leaked = False
    if isinstance(private, LearningItemCodePrivateV1):
        leaked = _answer_leaked(hints, private.standard_answer)
    elif isinstance(private, LearningItemSqlPrivateV1):
        leaked = _answer_leaked(hints, private.standard_query)
    elif isinstance(private, LearningItemKnowledgeCheckPrivateV1) and isinstance(public, LearningItemKnowledgeCheckContentV1):
        labels = {item.option_id: item.label for item in public.options}
        leaked = any(
            _contains_answer(hints, labels.get(answer, answer))
            for answer in private.accepted_answers
        )
    elif isinstance(private, LearningItemModelReviewPrivateV1):
        normalized = _normalized(hints)
        leaked = any(_normalized(item.finding_key) in normalized for item in private.rubric.expected_findings)
    if leaked:
        return _bad("hint_answer_leakage", {"hint_count": len(source.public.hints)})
    return _ok({"hint_count": len(source.public.hints), "hint_hash": canonical_hash(hints)})


def _answer_leaked(hints: str, answer: str) -> bool:
    hint_norm = _normalized(hints)
    answer_norm = _normalized(answer)
    if len(answer_norm) >= 20 and answer_norm in hint_norm:
        return True
    answer_tokens = _tokens(answer)
    hint_tokens = _tokens(hints)
    return len(answer_tokens) >= 6 and len(answer_tokens & hint_tokens) / len(answer_tokens) >= 0.85


def _contains_answer(hints: str, answer: str) -> bool:
    candidate = _normalized(answer)
    return len(candidate) >= 3 and candidate in _normalized(hints)


def _practice(source: LearningItemSourceV1) -> _Outcome:
    try:
        material = build_exercise_authority(source)
        if material is None:
            return _na(source.public.kind)
        report = require_exercise_quality(
            material.exercise,
            material.rubric,
            model_review_validation=material.model_review_validation,
        )
    except (TypeError, ValueError):
        return _bad("practice_contract_invalid")
    return _ok({"exercise_hash": report.exercise_hash, "rubric_hash": report.rubric_hash})


def _standard_answer(source: LearningItemSourceV1) -> _Outcome:
    result = _run_submission(source, standard=True)
    if result is None:
        return _na(source.public.kind)
    if not result[0]:
        return _bad("standard_answer_failed", {"runtime_status": result[1], "test_count": result[2]})
    return _ok({"runtime_status": result[1], "test_count": result[2]})


def _starter(source: LearningItemSourceV1) -> _Outcome:
    result = _run_submission(source, standard=False)
    if result is None:
        return _na(source.public.kind)
    if result[0]:
        return _bad("starter_already_passing", {"runtime_status": result[1], "test_count": result[2]})
    return _ok({"runtime_status": result[1], "test_count": result[2]})


def _run_submission(source: LearningItemSourceV1, *, standard: bool) -> tuple[bool, str, int] | None:
    material = build_exercise_authority(source)
    if material is None:
        return None
    payload = material.runner_payload
    content = source.public.content
    private = source.private.content
    try:
        if isinstance(content, LearningItemCodeContentV1) and isinstance(private, LearningItemCodePrivateV1):
            if source.blueprint.runtime_profile_id != "browser_preview":
                return False, "unsupported", len(private.tests)
            submission = material.standard_submission if standard else material.starter_submission
            blanks = _filled_blanks(content, submission)
            result = execute_browser_preview_with_tests(payload, submission, blanks)
            passed = result.status == "success" and result.logic_pass and all(item.passed for item in result.test_results)
            return passed, result.status, len(result.test_results)
        if isinstance(content, LearningItemSqlContentV1) and isinstance(private, LearningItemSqlPrivateV1):
            if source.blueprint.runtime_profile_id != "sql_query_test":
                return False, "unsupported", len(private.tests)
            query = material.standard_submission if standard else material.starter_submission
            if not _sql_read_only(query) or any(
                not _safe_setup(statement) for statement in private.setup_sql
            ):
                return False, "invalid", len(private.tests)
            cases = [item.model_dump(mode="json") for item in private.tests]
            metadata = payload.get("metadata_json", {})
            sql_result = execute_sql_query_with_tests(
                query,
                cases,
                metadata=metadata if isinstance(metadata, Mapping) else {},
            )
            passed = sql_result.status == "success" and all(item.passed for item in sql_result.test_results)
            return passed, sql_result.status, len(sql_result.test_results)
    except (TypeError, ValueError, re.error):
        return False, "invalid", 0
    return None


def _filled_blanks(content: LearningItemCodeContentV1, submission: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for blank in content.code_blanks:
        for pattern in blank.acceptable_patterns:
            if pattern.type == "literal" and pattern.value in submission:
                values[blank.blank_key] = pattern.value
                break
            if pattern.type == "regex":
                match = re.search(pattern.value, submission, flags=re.MULTILINE)
                if match is not None:
                    values[blank.blank_key] = match.group(0)
                    break
    return values


def _runtime_or_event(source: LearningItemSourceV1) -> _Outcome:
    public = source.public.content
    private = source.private.content
    if isinstance(public, LearningItemCodeContentV1) and isinstance(private, LearningItemCodePrivateV1):
        if source.blueprint.runtime_profile_id != "browser_preview":
            return _bad("deterministic_runtime_unsupported")
        expected_family = "static_preview" if public.language_id in {"html", "html_css", "css"} else "js_event_flow"
        if public.browser_rule_family != expected_family:
            return _bad("browser_rule_family_mismatch")
        try:
            for blank in public.code_blanks:
                for pattern in blank.acceptable_patterns:
                    if pattern.type == "regex":
                        re.compile(pattern.value)
        except re.error:
            return _bad("code_pattern_invalid")
        return _ok({"runtime_profile": "browser_preview", "rule_family": expected_family})
    if isinstance(public, LearningItemSqlContentV1) and isinstance(private, LearningItemSqlPrivateV1):
        if source.blueprint.runtime_profile_id != "sql_query_test":
            return _bad("runtime_profile_mismatch")
        if _sql_read_only(private.standard_query) is False or _sql_read_only(public.starter_query) is False:
            return _bad("sql_query_not_read_only")
        if any(not _safe_setup(statement) for statement in private.setup_sql):
            return _bad("sql_setup_unsafe")
        if any(not _sql_expected_shape(item.expected_output_json) for item in private.tests):
            return _bad("sql_result_expectation_invalid")
        return _ok({"setup_count": len(private.setup_sql), "test_count": len(private.tests)})
    if isinstance(public, LearningItemDemoContentV1) and isinstance(private, LearningItemDemoPrivateV1):
        if source.blueprint.runtime_profile_id != "browser_preview":
            return _bad("runtime_profile_mismatch")
        if public.completion_mode == "exact_event":
            if public.expected_event is None or private.expected_events != (public.expected_event,):
                return _bad("demo_event_contract_mismatch")
        elif private.expected_events or public.duration_seconds is None:
            return _bad("demo_duration_contract_mismatch")
        return _ok({"completion_mode": public.completion_mode})
    return _na(source.public.kind)


def _sql_read_only(query: str) -> bool:
    cleaned = re.sub(r"--[^\n]*|/\*.*?\*/|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"", " ", query, flags=re.DOTALL)
    tokens = [item.casefold() for item in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", cleaned)]
    statements = [part for part in cleaned.split(";") if part.strip()]
    return (
        bool(tokens)
        and tokens[0] in {"select", "with"}
        and not (_SQL_UNSAFE & set(tokens))
        and len(statements) == 1
    )


def _safe_setup(statement: str) -> bool:
    cleaned = re.sub(
        r"--[^\n]*|/\*.*?\*/|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"",
        " ",
        statement,
        flags=re.DOTALL,
    )
    if len([part for part in cleaned.split(";") if part.strip()]) != 1:
        return False
    tokens = [
        item.casefold()
        for item in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", cleaned)
    ]
    if tokens[:2] == ["create", "table"]:
        forbidden = {
            "as",
            "attach",
            "check",
            "default",
            "generated",
            "load_extension",
            "pragma",
            "select",
            "temp",
            "temporary",
            "trigger",
            "virtual",
            "with",
        }
        return not (forbidden & set(tokens))
    if tokens[:2] == ["insert", "into"] and tokens.count("values") == 1:
        values_index = tokens.index("values")
        return not any(
            token not in {"false", "null", "true"}
            for token in tokens[values_index + 1 :]
        )
    return False


def _sql_expected_shape(value: Mapping[str, object]) -> bool:
    columns = value.get("columns")
    rows = value.get("rows")
    return (
        isinstance(columns, Sequence)
        and not isinstance(columns, str)
        and all(isinstance(item, str) and item for item in columns)
        and isinstance(rows, Sequence)
        and not isinstance(rows, str)
        and all(isinstance(item, Mapping) for item in rows)
    )


def _scorer(source: LearningItemSourceV1) -> _Outcome:
    public = source.public.content
    private = source.private.content
    if isinstance(private, (LearningItemCodePrivateV1, LearningItemSqlPrivateV1)):
        if private.score_policy.kind != "all_tests" or private.score_policy.threshold != 1:
            return _bad("scorer_contract_invalid")
        return _ok({"policy_version": private.score_policy.policy_version, "threshold": 1.0})
    if isinstance(public, LearningItemKnowledgeCheckContentV1) and isinstance(private, LearningItemKnowledgeCheckPrivateV1):
        error = _knowledge_error(public, private)
        if error is not None:
            return _bad(error)
        return _ok({"accepted_count": len(private.accepted_answers), "policy_version": private.score_policy.policy_version})
    if isinstance(public, LearningItemModelReviewContentV1) and isinstance(private, LearningItemModelReviewPrivateV1):
        try:
            material = build_exercise_authority(source)
            if material is None or material.model_review_validation is None:
                return _bad("model_review_receipt_missing")
            if material.model_review_validation.candidate_hash != candidate_hash(material.exercise, material.rubric):
                return _bad("model_review_receipt_stale")
            require_model_review_quality(material.exercise, material.rubric, material.model_review_validation)
            result = evaluate_model_code_review(
                submission=private.reference_submission,
                rubric=private.rubric,
                line_count=public.artifact.line_count,
                required_capabilities=source.blueprint.required_capabilities,
                assistance_kind=ModelReviewAssistanceKind.INDEPENDENT,
                threshold=private.score_policy.threshold,
                now=datetime(2000, 1, 1, tzinfo=UTC),
            )
        except (TypeError, ValueError):
            return _bad("model_review_scorer_invalid")
        if (
            private.reference_submission.verdict is not private.rubric.expected_verdict
            or private.score_policy.policy_version != MODEL_REVIEW_SCORE_POLICY_VERSION
            or result.outcome.value != "passed"
            or result.policy_version != private.score_policy.policy_version
        ):
            return _bad("model_review_scorer_mismatch")
        return _ok({"candidate_hash": material.model_review_validation.candidate_hash, "score": result.score, "receipt_hash": material.model_review_validation.receipt_hash})
    return _na(source.public.kind)


def _knowledge_error(public: LearningItemKnowledgeCheckContentV1, private: LearningItemKnowledgeCheckPrivateV1) -> str | None:
    option_ids = {item.option_id for item in public.options}
    accepted = tuple(private.accepted_answers)
    if public.response_kind == "single_choice" and (len(accepted) != 1 or accepted[0] not in option_ids):
        return "knowledge_answer_not_unique"
    if public.response_kind == "multiple_choice" and (len(accepted) < 2 or not set(accepted) <= option_ids):
        return "knowledge_answer_not_unique"
    if public.response_kind == "short_text":
        stronger = tuple(_normalized_answer(item) for item in accepted)
        if len(stronger) != len(set(stronger)):
            return "knowledge_answer_not_unique"
    for test in private.tests:
        answer = test.input_json.get("answer")
        expected = test.expected_output_json.get("accepted")
        if isinstance(answer, str) and isinstance(expected, bool):
            if expected != (answer in accepted):
                return "knowledge_test_expectation_mismatch"
    if private.score_policy.kind != "static_exact" or private.score_policy.threshold != 1:
        return "scorer_contract_invalid"
    return None


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _normalized_answer(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", normalize_answer(unicodedata.normalize("NFKC", value)))


def _tokens(value: str) -> frozenset[str]:
    return frozenset(item.casefold() for item in _TOKEN.findall(unicodedata.normalize("NFKC", value)))


__all__ = ("validate_learning_item",)
