"""Explicit stage policy for new completion-driven runs, never legacy activation.

The channel capacity is an operator's validated declaration, not a provider
probe or proof of loaded runtime configuration. Without it, the existing
application input envelope remains the conservative fallback. Advertised model
windows do not authorize filling that window.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from math import ceil
from typing import Literal, cast, get_args

from app.agents.harness.context_builder import Utf8ByteTokenEstimator
from app.agents.harness.contracts import (
    TUTOR_COMPLETION_CONTEXT_SAFETY_MARGIN_RATIO as COMPLETION_SAFETY_MARGIN_RATIO,
    TokenEstimator, TutorProviderContextCapability,
)
from app.core.config import Settings


CompletionStage = Literal[
    "tutor_decision", "material_semantic_review", "lesson_authoring",
    "model_review_authoring", "sidecar_turn",
]
COMPLETION_MAX_HTTP_SECONDS = 600.0
COMPLETION_MIN_SAFETY_MARGIN_TOKENS = 4096


@dataclass(frozen=True)
class CompletionStagePolicy:
    stage: CompletionStage
    max_output_tokens: int | None
    timeout_seconds: float
    context_capability: TutorProviderContextCapability | None
    thinking_mode: Literal["disabled"] | None = None


def resolve_completion_stage_policy(settings: Settings, stage: str) -> CompletionStagePolicy:
    """Resolve declared settings only; callers still gate new-run activation.

    Sidecar has no supported exact output-token wire control. Its absent output
    and context capability are deliberate, not an unlimited token allowance.
    """
    if stage not in get_args(CompletionStage):
        raise ValueError("Unknown completion stage")
    typed_stage = cast(CompletionStage, stage)
    if stage == "sidecar_turn":
        return CompletionStagePolicy(
            typed_stage, None, float(settings.tutor_completion_sidecar_timeout_seconds), None,
        )
    if stage == "tutor_decision":
        output = settings.tutor_completion_decision_max_output_tokens
        timeout = settings.tutor_completion_decision_timeout_seconds
    elif stage == "material_semantic_review":
        output = settings.tutor_completion_semantic_max_output_tokens
        timeout = settings.tutor_completion_semantic_timeout_seconds
    elif stage == "lesson_authoring":
        output = settings.tutor_completion_lesson_max_output_tokens
        timeout = settings.tutor_completion_lesson_timeout_seconds
    else:
        output = settings.tutor_completion_model_review_max_output_tokens
        timeout = settings.tutor_completion_model_review_timeout_seconds

    if settings.uses_deepseek_v4_flash_responses:
        model_window = settings.tutor_deepseek_v4_flash_context_window_tokens
        model_output = settings.tutor_deepseek_v4_flash_max_output_tokens
        legacy_input = settings.tutor_deepseek_v4_flash_input_limit_tokens
    else:
        model_window = settings.tutor_default_context_window_tokens
        model_output = settings.tutor_default_output_reserve_tokens
        legacy_input = model_window - model_output
    if output > model_output:
        raise ValueError("Completion stage output exceeds configured model output capacity")
    channel_window = settings.tutor_completion_validated_channel_context_tokens
    if channel_window is None:
        # A smaller stage output is not evidence for increasing the old input cap.
        window = min(model_window, legacy_input + output)
        version = "completion-legacy-application-fallback-v1"
    else:
        window = min(model_window, channel_window)
        version = "completion-declared-validated-channel-v1"
    protocol = settings.tutor_context_protocol_reserve_tokens
    margin = max(COMPLETION_MIN_SAFETY_MARGIN_TOKENS, settings.tutor_context_safety_margin_tokens)
    available = window - output - protocol
    target = min(available - margin, int(available / (1 + COMPLETION_SAFETY_MARGIN_RATIO)))
    capability = TutorProviderContextCapability(
        context_window_tokens=window,
        max_output_reserve_tokens=output,
        protocol_reserve_tokens=protocol,
        safety_margin_tokens=margin,
        maximum_dynamic_target_tokens=target,
        capability_version=version,
    )
    return CompletionStagePolicy(
        typed_stage, output, float(timeout), capability,
        "disabled" if stage == "material_semantic_review" else None,
    )


def estimate_completion_request_tokens(
    request: object, *, capability: TutorProviderContextCapability,
    estimator: TokenEstimator | None = None,
) -> int:
    """One shared, explicitly heuristic estimate of the exact JSON representation.

    The caller supplies the actual wire payload (including schemas/protocol) for
    completion requests. Legacy callers may still pass their message list.
    Output is already reserved by capability.input_hard_limit.
    """
    serialized = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
    estimate = max(1, (estimator or Utf8ByteTokenEstimator()).estimate_tokens(serialized))
    margin = max(capability.safety_margin_tokens, ceil(estimate * capability.safety_margin_ratio))
    return estimate + capability.protocol_reserve_tokens + margin
