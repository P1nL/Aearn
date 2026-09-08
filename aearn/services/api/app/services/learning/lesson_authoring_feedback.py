"""Closed, content-free diagnostics for the single Lesson repair attempt."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

# Constraints are server-owned. Never copy exception text or candidate values.
CONSTRAINTS = {
    "LESSON_PROVIDER_ENVELOPE_INVALID": "Return one complete structured JSON response.",
    "LESSON_PROVIDER_CONTENT_MISSING": "Return a non-empty LessonDocument JSON object.",
    "LESSON_PROVIDER_CONTENT_NOT_JSON_OBJECT": "Return only one JSON object, without surrounding text.",
    "LESSON_PROVIDER_RESPONSE_INCOMPLETE": "Return a shorter complete JSON object within the output limit.",
    "LESSON_PROVIDER_RESPONSE_FAILED": "The provider reported failure; no automatic repair is allowed.",
    "LESSON_PROVIDER_UNKNOWN": "The provider response could not be classified safely.",
    "LESSON_PROVIDER_UNAVAILABLE": "The configured provider is unavailable.",
    "LESSON_AUTHOR_INTERNAL_FAILURE": "Authoring stopped because of an internal failure.",
    "LESSON_DOCUMENT_FIELDS_INVALID": "Use exactly the registered document fields and their required types and limits.",
    "LESSON_BLOCK_FIELDS_INVALID": "Use exactly the registered block fields, types, lengths and enum values shown in the block examples.",
    "LESSON_BLOCK_TYPE_INVALID": "Use only a registered block type shown in the block examples.",
    "LESSON_BLOCK_ORDER_INVALID": "Use unique block IDs and continuous order_index values starting at zero.",
    "LESSON_CITATION_HANDLE_INVALID": "citation_ids must be a unique array containing only supplied evidence handles.",
    "LESSON_CANDIDATE_SCOPE_INVALID": "Preserve the requested language_id and knowledge_key exactly.",
    "LESSON_HEADING_REQUIRED": "Include a heading block.",
    "LESSON_OBJECTIVES_REQUIRED": "Include a learning_objectives block.",
    "LESSON_CONCEPT_REQUIRED": "Include a concept block.",
    "LESSON_SUMMARY_REQUIRED": "Include a summary block.",
    "LESSON_CITATION_NOT_FOUND": "Cite only the supplied evidence handles.",
    "LESSON_CITATION_REQUIRED": "Every factual block must cite supplied evidence.",
    "LESSON_AUTHORITY_SOURCE_REQUIRED": "An authority_note must cite an official evidence handle.",
    "LESSON_CODE_LANGUAGE_MISMATCH": "Code examples must use the requested course language.",
    "LESSON_EXECUTION_CLAIM_FORBIDDEN": "execution_claim must be not_run.",
    "LESSON_GATE_DUPLICATE": "Each exercise_gate must have a unique gate_key.",
    "LESSON_COVERAGE_INCOMPLETE": "Cover every document coverage key in objectives, concepts, summaries or Gates.",
    "LESSON_SENSITIVE_CONTENT_FORBIDDEN": "Remove executable HTML, scripts, styles and all internal or protected content.",
    "LESSON_PERSONALIZED_SCOPE_MISMATCH": "Preserve the validated standard language and knowledge scope.",
    "LESSON_PERSONALIZED_COVERAGE_REDUCED": "Preserve all validated standard coverage keys.",
    "LESSON_PERSONALIZED_GATE_CHANGED": "Copy every validated standard exercise_gate contract exactly.",
    "LESSON_SOURCE_DUPLICATE": "Source integrity validation failed.",
    "LESSON_SOURCE_NOT_REGISTERED": "Source integrity validation failed.",
    "LESSON_SOURCE_LANGUAGE_MISMATCH": "Source integrity validation failed.",
    "LESSON_SOURCE_REGISTRY_MISMATCH": "Source integrity validation failed.",
    "LESSON_SOURCE_URL_NOT_ALLOWLISTED": "Source integrity validation failed.",
    "LESSON_SOURCE_HASH_SEMANTICS_INVALID": "Source integrity validation failed.",
    "LESSON_STANDARD_LINEAGE_REQUIRED": "Standard lineage validation failed.",
    "LESSON_STANDARD_LINEAGE_INVALID": "Standard lineage validation failed.",
}
REPAIRABLE = frozenset({
    "LESSON_PROVIDER_ENVELOPE_INVALID", "LESSON_PROVIDER_CONTENT_MISSING",
    "LESSON_PROVIDER_CONTENT_NOT_JSON_OBJECT", "LESSON_PROVIDER_RESPONSE_INCOMPLETE",
    "LESSON_DOCUMENT_FIELDS_INVALID", "LESSON_BLOCK_FIELDS_INVALID", "LESSON_BLOCK_TYPE_INVALID",
    "LESSON_BLOCK_ORDER_INVALID", "LESSON_CITATION_HANDLE_INVALID", "LESSON_CANDIDATE_SCOPE_INVALID",
    "LESSON_HEADING_REQUIRED", "LESSON_OBJECTIVES_REQUIRED", "LESSON_CONCEPT_REQUIRED",
    "LESSON_SUMMARY_REQUIRED", "LESSON_CITATION_NOT_FOUND", "LESSON_CITATION_REQUIRED",
    "LESSON_AUTHORITY_SOURCE_REQUIRED", "LESSON_CODE_LANGUAGE_MISMATCH", "LESSON_EXECUTION_CLAIM_FORBIDDEN",
    "LESSON_GATE_DUPLICATE", "LESSON_COVERAGE_INCOMPLETE", "LESSON_SENSITIVE_CONTENT_FORBIDDEN",
    "LESSON_PERSONALIZED_SCOPE_MISMATCH", "LESSON_PERSONALIZED_COVERAGE_REDUCED",
    "LESSON_PERSONALIZED_GATE_CHANGED",
})
STAGES = frozenset({"provider_response", "candidate_shape", "candidate_contract", "candidate_identity", "quality_gate"})
_LOCATION = re.compile(r"(?:document|blocks(?:\[(?:[0-9]|[1-5][0-9]|6[0-3])\])?(?:\.(?:citation_ids|type|order_index))?|language_id|knowledge_key)")


@dataclass(frozen=True, slots=True)
class LessonFeedbackIssue:
    code: str
    location: str = "document"

    def __post_init__(self) -> None:
        if self.code not in CONSTRAINTS or not _LOCATION.fullmatch(self.location):
            raise ValueError("Invalid Lesson feedback issue")

    def payload(self) -> dict[str, object]:
        return {"code": self.code, "location": self.location, "constraint": CONSTRAINTS[self.code]}


@dataclass(frozen=True, slots=True)
class LessonAuthorFeedback:
    document_kind: str
    failed_stage: str
    previous_attempt_index: int
    issues: tuple[LessonFeedbackIssue, ...]

    def __post_init__(self) -> None:
        if self.document_kind not in {"standard", "personalized"} or self.failed_stage not in STAGES:
            raise ValueError("Invalid Lesson feedback scope")
        if type(self.previous_attempt_index) is not int or self.previous_attempt_index not in {1, 2}:
            raise ValueError("Invalid Lesson feedback attempt")
        if not 1 <= len(self.issues) <= 12:
            raise ValueError("Lesson feedback requires 1..12 issues")

    @property
    def repairable(self) -> bool:
        return all(issue.code in REPAIRABLE for issue in self.issues)

    def payload(self) -> dict[str, object]:
        return {"schema_version": "lesson_author_feedback_v1", "document_kind": self.document_kind,
                "failed_stage": self.failed_stage, "previous_attempt_index": self.previous_attempt_index,
                "issues": [issue.payload() for issue in self.issues]}

    @property
    def content_hash(self) -> str:
        encoded = json.dumps(self.payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()


def attempt_diagnostic(document_kind: str, attempt: int, feedback: LessonAuthorFeedback | None = None) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "lesson_author_attempt_diagnostic_v1", "document_kind": document_kind,
        "document_attempt_index": attempt, "failure_stage": feedback.failed_stage if feedback else None,
        "issue_codes": [issue.code for issue in feedback.issues] if feedback else [],
        "issue_locations": [issue.location for issue in feedback.issues] if feedback else [],
        "feedback_hash": feedback.content_hash if feedback else None,
    }
    return validate_attempt_diagnostic(value)


def validate_attempt_diagnostic(value: Mapping[str, object]) -> dict[str, object]:
    if not value:  # Legacy receipts have no diagnostic.
        return {}
    expected = {"schema_version", "document_kind", "document_attempt_index", "failure_stage", "issue_codes", "issue_locations", "feedback_hash"}
    if set(value) != expected or value["schema_version"] != "lesson_author_attempt_diagnostic_v1":
        raise ValueError("Invalid Lesson diagnostic shape")
    if value["document_kind"] not in ("standard", "personalized") or type(value["document_attempt_index"]) is not int or value["document_attempt_index"] not in (1, 2):
        raise ValueError("Invalid Lesson diagnostic scope")
    codes, locations = value["issue_codes"], value["issue_locations"]
    if not isinstance(codes, list) or not isinstance(locations, list) or len(codes) != len(locations) or len(codes) > 12:
        raise ValueError("Invalid Lesson diagnostic issues")
    for code, location in zip(codes, locations, strict=True):
        if not isinstance(code, str) or not isinstance(location, str):
            raise ValueError("Invalid Lesson diagnostic issue")
        LessonFeedbackIssue(code, location)
    stage, digest = value["failure_stage"], value["feedback_hash"]
    if codes:
        if not isinstance(stage, str) or stage not in STAGES or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid Lesson diagnostic failure")
    elif stage is not None or digest is not None:
        raise ValueError("Invalid Lesson diagnostic success")
    return {**value, "issue_codes": list(codes), "issue_locations": list(locations)}
