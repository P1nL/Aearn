"""PRIVATE closed failure metadata. Not usage settlement or admission authority."""
from __future__ import annotations

import http.client
import urllib.error
from dataclasses import asdict, dataclass, replace
from typing import Literal, get_args

from pydantic import ValidationError

from app.services.learning.item_bank.contracts import LearningItemReviewRole
from app.services.llm.contracts import LLMResponseDiagnostics, LLMUsage
from app.services.llm.llm_client import (
    LLMCallError, LLMConfigurationError, LLMInvalidResponseError, LLMInvalidResponseKind,
)

ReviewFailurePhase = Literal[
    "provider_call", "output_schema", "evidence_verification", "review_bundle",
    "blind_score", "finite_ambiguity",
]
ReviewFailureCode = Literal[
    "provider_timeout", "provider_transport", "provider_configuration",
    "response_incomplete", "response_failed", "response_missing", "response_non_json",
    "response_envelope_invalid", "schema_validation", "evidence_verification",
    "provider_binding_mismatch", "output_limit", "unknown_exception",
]


def _usage(value: object) -> LLMUsage | None:
    if type(value) is not LLMUsage:
        return None
    try:
        return LLMUsage(**asdict(value))
    except (TypeError, ValueError):
        return None


def _diagnostics(value: object) -> LLMResponseDiagnostics | None:
    if type(value) is not LLMResponseDiagnostics:
        return None
    try:
        return LLMResponseDiagnostics(**asdict(value))
    except (TypeError, ValueError):
        return None


def merge_response_diagnostics(
    actual: LLMResponseDiagnostics | None, requested: LLMResponseDiagnostics | None,
) -> LLMResponseDiagnostics | None:
    actual, requested = _diagnostics(actual), _diagnostics(requested)
    if actual is None:
        return requested
    if requested is None:
        return actual
    # Only fill trusted request limits, never manufacture stop/completion facts.
    return replace(actual,
        requested_max_output_tokens=(actual.requested_max_output_tokens if actual.requested_max_output_tokens is not None
                                     else requested.requested_max_output_tokens),
        requested_reasoning_effort=(actual.requested_reasoning_effort if actual.requested_reasoning_effort is not None
                                   else requested.requested_reasoning_effort))


@dataclass(frozen=True, repr=False)
class ReviewFailureObservation:
    phase: ReviewFailurePhase
    failed_role: LearningItemReviewRole | None
    safe_code: ReviewFailureCode
    usage: LLMUsage | None = None
    response_diagnostics: LLMResponseDiagnostics | None = None
    # Attested only at the actual adapter client invocation. NOT HTTP attempts,
    # reservation sizes, aggregate bundle usage or complete per-attempt accounting.
    logical_client_invocations: int | None = None

    def __post_init__(self) -> None:
        if (type(self.phase) is not str or self.phase not in get_args(ReviewFailurePhase)
                or type(self.safe_code) is not str or self.safe_code not in get_args(ReviewFailureCode)
                or (self.failed_role is not None and type(self.failed_role) is not LearningItemReviewRole)
                or (self.logical_client_invocations is not None
                    and (type(self.logical_client_invocations) is not int or self.logical_client_invocations != 1))):
            raise ValueError("invalid_review_observation")
        if self.usage is not None and _usage(self.usage) != self.usage:
            raise ValueError("invalid_review_observation")
        if self.response_diagnostics is not None and _diagnostics(self.response_diagnostics) != self.response_diagnostics:
            raise ValueError("invalid_review_observation")

    def payload(self) -> dict[str, object]:
        # Revalidate on projection so even illicit frozen-object mutation cannot
        # introduce arbitrary text. No exception, model or provider body is read.
        checked = replace(self)
        return {
            "schema_version": "item_supply_review_failure_observation_v1",
            "phase": checked.phase,
            "failed_role": checked.failed_role.value if checked.failed_role is not None else None,
            "safe_code": checked.safe_code,
            "usage": asdict(checked.usage) if checked.usage is not None else None,
            "response_diagnostics": asdict(checked.response_diagnostics) if checked.response_diagnostics is not None else None,
            "logical_client_invocations": checked.logical_client_invocations,
            "invocation_count_scope": "failed_adapter_operation",
            "invocation_count_semantics": "logical_client_invocations_not_http_attempts",
        }


def _timeout_cause(exc: Exception) -> bool:
    current: BaseException | None = exc
    for _ in range(4):
        if isinstance(current, TimeoutError):
            return True
        if isinstance(current, urllib.error.URLError) and isinstance(current.reason, TimeoutError):
            return True
        # Only traverse wrappers actually produced by the trusted transport.
        if not isinstance(current, (LLMCallError, urllib.error.URLError)):
            break
        current = current.__cause__
    return False


def observe_review_failure(
    exc: Exception, *, phase: ReviewFailurePhase, failed_role: LearningItemReviewRole | None = None,
    usage: LLMUsage | None = None, response_diagnostics: LLMResponseDiagnostics | None = None,
    logical_client_invocations: int | None = None,
    safe_code: ReviewFailureCode | None = None,
) -> ReviewFailureObservation:
    """Map by type/closed enum only. Never inspect messages or raw validation errors."""
    if safe_code is None:
        if isinstance(exc, LLMInvalidResponseError):
            usage = _usage(exc.usage) or _usage(usage)
            response_diagnostics = merge_response_diagnostics(exc.response_diagnostics, response_diagnostics)
            codes: dict[LLMInvalidResponseKind, ReviewFailureCode] = {
                LLMInvalidResponseKind.RESPONSE_INCOMPLETE: "response_incomplete",
                LLMInvalidResponseKind.RESPONSE_FAILED: "response_failed",
                LLMInvalidResponseKind.CONTENT_MISSING: "response_missing",
                LLMInvalidResponseKind.CONTENT_NOT_JSON_OBJECT: "response_non_json",
                LLMInvalidResponseKind.ENVELOPE_INVALID: "response_envelope_invalid",
                LLMInvalidResponseKind.UNKNOWN: "unknown_exception",
            }
            safe_code = codes.get(exc.kind, "unknown_exception") if type(exc.kind) is LLMInvalidResponseKind else "unknown_exception"
            if response_diagnostics is not None and response_diagnostics.response_status == "missing_terminal":
                safe_code = "response_missing"
        elif isinstance(exc, LLMConfigurationError):
            safe_code = "provider_configuration"
        elif _timeout_cause(exc):
            safe_code = "provider_timeout"
        elif isinstance(exc, (LLMCallError, urllib.error.URLError, ConnectionError, http.client.HTTPException)):
            safe_code = "provider_transport"
        elif isinstance(exc, ValidationError):
            safe_code = "schema_validation"
        else:
            safe_code = "unknown_exception"
    return ReviewFailureObservation(phase, failed_role, safe_code, _usage(usage), _diagnostics(response_diagnostics),
                                    logical_client_invocations)
