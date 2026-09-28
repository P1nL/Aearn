"""Final per-attempt Tutor provider wire-size guard.

The context planner bounds the original serialized messages. A retry may append
repair guidance after that selection, so the gateway must recheck the exact list
it is about to send, rather than trusting checkpoint metadata from attempt one.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from app.agents.harness.context_builder import Utf8ByteTokenEstimator
from app.agents.harness.contracts import (
    TokenEstimator,
    TutorContextError,
    TutorProviderContextCapability,
)


def assert_tutor_provider_request_budget(
    messages: Sequence[Mapping[str, str]],
    *,
    capability: TutorProviderContextCapability,
    estimator: TokenEstimator | None = None,
) -> int:
    """Return the full input estimate, or deny before a provider call.

    Use the planner's exact JSON representation, estimator, protocol/safety
    reserves, and input ceiling. The ceiling already subtracts the configured
    output reserve from the context window; no second output subtraction is made.
    """
    serialized = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    estimate = (
        max(1, (estimator or Utf8ByteTokenEstimator()).estimate_tokens(serialized))
        + capability.protocol_reserve_tokens
        + capability.safety_margin_tokens
    )
    if estimate > capability.input_hard_limit:
        raise TutorContextError("TUTOR_CONTEXT_REQUEST_OVERFLOW")
    return estimate
