"""Final per-attempt Tutor provider wire-size guard.

The context planner bounds the original serialized messages. A retry may append
repair guidance after that selection, so the gateway must recheck the exact list
it is about to send, rather than trusting checkpoint metadata from attempt one.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.agents.harness.contracts import (
    TokenEstimator,
    TutorContextError,
    TutorProviderContextCapability,
)
from app.services.llm.completion_policy import estimate_completion_request_tokens


def assert_tutor_provider_request_budget(
    messages: Sequence[Mapping[str, str]],
    *,
    capability: TutorProviderContextCapability,
    estimator: TokenEstimator | None = None,
    payload: Mapping[str, object] | None = None,
) -> int:
    """Return the full input estimate, or deny before a provider call.

    Use the planner's exact JSON representation, estimator, protocol/safety
    reserves, and input ceiling. The ceiling already subtracts the configured
    output reserve from the context window; no second output subtraction is made.
    """
    estimate = estimate_completion_request_tokens(
        payload if payload is not None else messages,
        capability=capability, estimator=estimator,
    )
    if estimate > capability.input_hard_limit:
        raise TutorContextError("TUTOR_CONTEXT_REQUEST_OVERFLOW")
    return estimate
