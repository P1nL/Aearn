"""Primary-only model gateway for the feature-disabled Tutor Harness."""
from __future__ import annotations

import json
import logging
import socket
import urllib.error
from collections.abc import Mapping, Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.agents.harness.contracts import (
    MAX_TUTOR_PAYLOAD_FIELDS,
    MAX_TUTOR_PUBLIC_MESSAGE_LENGTH,
    TutorCapabilityRequest,
    TutorCheckpointReason,
    TutorContinuationKind,
    TutorContextSelection,
    TutorDecision,
    TutorEffectProposal,
    TutorProviderResult,
    TutorRunSnapshot,
    TutorSkillReference,
    TutorTerminalOutcome,
    payload_fields_from_mapping,
)
from app.core.config import Settings, get_settings
from app.core.teaching_safety import check_teaching_output
from app.services.llm.llm_client import (
    LLMCallError,
    LLMConfigurationError,
    LLMInvalidResponseError,
    LLMInvalidResponseKind,
    LLMJsonResponse,
    OpenAICompatibleClient,
)


logger = logging.getLogger(__name__)


PRIMARY_PROVIDER_DECISION_ATTEMPTS = 2

_TUTOR_TEACHING_POLICY = (
    "When current_input is present, treat it as the authoritative request for this TurnRun and answer or acknowledge it "
    "before advancing any earlier lesson, exercise, setup, or plan. Prior context is supporting evidence only. "
    "A learner correction, interruption, refusal, goal change, or statement that a step is already complete overrides stale "
    "assumptions: briefly acknowledge the change, stop the stale path, and do not repeat completed or rejected steps unless "
    "the learner explicitly asks. For advice, comparison, capability, or what-to-learn questions, answer directly first and "
    "ask at most one necessary follow-up question. Do not force an earlier website, image, or HTML path merely because it "
    "appears in context. Be concise and learner-facing, and state uncertainty instead of inventing facts."
)

_PROVIDER_CONFIGURATION_UNAVAILABLE = "TUTOR_PROVIDER_CONFIGURATION_UNAVAILABLE"
_PROVIDER_TIMEOUT = "TUTOR_PROVIDER_TIMEOUT"
_PROVIDER_AUTH_FAILED = "TUTOR_PROVIDER_AUTH_FAILED"
_PROVIDER_QUOTA_UNAVAILABLE = "TUTOR_PROVIDER_QUOTA_UNAVAILABLE"
_PROVIDER_RATE_LIMITED = "TUTOR_PROVIDER_RATE_LIMITED"
_PROVIDER_HTTP_ERROR = "TUTOR_PROVIDER_HTTP_ERROR"
_PROVIDER_REQUEST_REJECTED = "TUTOR_PROVIDER_REQUEST_REJECTED"
_PROVIDER_REQUEST_FAILED = "TUTOR_PROVIDER_REQUEST_FAILED"
_PROVIDER_RESPONSE_ENVELOPE_INVALID = "TUTOR_PROVIDER_RESPONSE_ENVELOPE_INVALID"
_PROVIDER_RESPONSE_CONTENT_MISSING = "TUTOR_PROVIDER_RESPONSE_CONTENT_MISSING"
_PROVIDER_RESPONSE_CONTENT_NOT_JSON = "TUTOR_PROVIDER_RESPONSE_CONTENT_NOT_JSON"
_PROVIDER_RESPONSE_INCOMPLETE = "TUTOR_PROVIDER_RESPONSE_INCOMPLETE"
_PROVIDER_RESPONSE_FAILED = "TUTOR_PROVIDER_RESPONSE_FAILED"
_PROVIDER_RESPONSE_INVALID = "TUTOR_PROVIDER_RESPONSE_INVALID"
_PROVIDER_DECISION_INVALID = "TUTOR_PROVIDER_DECISION_INVALID"
_PROVIDER_OUTPUT_SAFETY_REJECTED = "TUTOR_PROVIDER_OUTPUT_SAFETY_REJECTED"
_PROVIDER_ADAPTER_FAILED = "TUTOR_PROVIDER_ADAPTER_FAILED"

_REPAIRABLE_INVALID_RESPONSE_KINDS = frozenset(
    {
        LLMInvalidResponseKind.CONTENT_MISSING,
        LLMInvalidResponseKind.CONTENT_NOT_JSON_OBJECT,
    }
)


def _canonical_tutor_decision_example() -> str:
    """One frozen shape shared by the first request and the one permitted repair."""

    return json.dumps(
        {
            "public_message": "请从一个很小的练习开始。",
            "conversation_title": "函数基础练习",
            "skill_references": [],
            "capability_requests": [],
            "effect_proposals": [],
            "checkpoint_reason": None,
            "continuation_kind": None,
            "terminal_intent": "completed",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


# This reminder is deliberately generic: it helps the configured primary model
# repair a rejected candidate without echoing provider output or validation detail
# back into the prompt, logs, durable state, or public API.
_TUTOR_DECISION_REPAIR_MESSAGE = (
    "Your previous candidate was not accepted. Return a replacement now. "
    "Return exactly one JSON object and no Markdown or explanation. "
    "Use this exact complete shape (values may differ): "
    f"{_canonical_tutor_decision_example()} "
    "Use null when there is no optional value and empty arrays when there are no requests. "
    "A normal direct reply must use terminal_intent=completed and continuation_kind=null. "
    "A continuation_kind is allowed only with checkpoint_reason=capability_result and terminal_intent=null. "
    "Include only the listed keys and values needed for this decision. "
    f"Keep following this teaching policy: {_TUTOR_TEACHING_POLICY}"
)


class TutorDecisionValidationError(LLMInvalidResponseError):
    """The provider response is JSON-like but does not meet the Tutor decision contract."""


class TutorOutputSafetyError(LLMInvalidResponseError):
    """A learner-visible Tutor output failed the shared teaching safety policy."""


class TutorJsonClient(Protocol):
    @property
    def model(self) -> str: ...

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
    ) -> LLMJsonResponse: ...


def _assert_safe_tutor_output(text: str) -> None:
    check = check_teaching_output(text)
    if check.blocked:
        raise TutorOutputSafetyError("Tutor output failed the teaching safety policy")


_FORBIDDEN_NESTED_PAYLOAD_FIELD_NAMES = frozenset(
    {
        "reasoning",
        "diagnostic",
        "diagnostics",
        "solutionreference",
        "referenceanswer",
        "rawprompt",
        "systemprompt",
        "providerpayload",
        "providererror",
        "apikey",
        "secret",
        "secretkey",
        "authtoken",
        "stacktrace",
        "traceback",
    }
)


TutorEnvelopeValue = str | int | float | bool | None | list[str]


def _validate_nested_payload_fields(
    value: dict[str, TutorEnvelopeValue],
    *,
    label: str,
) -> dict[str, TutorEnvelopeValue]:
    if len(value) > MAX_TUTOR_PAYLOAD_FIELDS:
        raise ValueError(f"{label} exceed the bounded contract")
    for raw_key, raw_value in value.items():
        compact_key = "".join(character for character in raw_key.lower() if character.isalnum())
        if compact_key in _FORBIDDEN_NESTED_PAYLOAD_FIELD_NAMES or compact_key.startswith("hiddentest"):
            raise ValueError(f"{label} contain an internal-only field")
        if isinstance(raw_value, list) and (len(raw_value) > 4 or any(len(item) > 120 for item in raw_value)):
            raise ValueError(f"{label} contain an oversized list")
        _assert_safe_tutor_output(raw_key)
        _assert_safe_tutor_output(json.dumps(raw_value, ensure_ascii=False, sort_keys=True))
    return value


class _StrictEnvelopeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class _SkillReferencePayload(_StrictEnvelopeModel):
    skill_id: str = Field(min_length=1, max_length=120)
    version: str = Field(default="current", min_length=1, max_length=120)


class _CapabilityRequestPayload(_StrictEnvelopeModel):
    request_id: str = Field(min_length=1, max_length=120)
    capability_id: str = Field(min_length=1, max_length=120)
    arguments: dict[str, TutorEnvelopeValue] = Field(default_factory=dict)

    @field_validator("arguments")
    @classmethod
    def _validate_arguments(
        cls,
        value: dict[str, TutorEnvelopeValue],
    ) -> dict[str, TutorEnvelopeValue]:
        return _validate_nested_payload_fields(value, label="capability arguments")


class _EffectProposalPayload(_StrictEnvelopeModel):
    effect_id: str = Field(min_length=1, max_length=120)
    effect_type: str = Field(min_length=1, max_length=120)
    expected_input_revision: int = Field(ge=0)
    payload: dict[str, TutorEnvelopeValue] = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def _validate_payload(
        cls,
        value: dict[str, TutorEnvelopeValue],
    ) -> dict[str, TutorEnvelopeValue]:
        return _validate_nested_payload_fields(value, label="effect payload")


class _TutorDecisionEnvelope(_StrictEnvelopeModel):
    public_message: str | None = Field(default=None, max_length=MAX_TUTOR_PUBLIC_MESSAGE_LENGTH)
    conversation_title: str | None = Field(default=None, max_length=48)
    skill_references: list[_SkillReferencePayload] = Field(default_factory=list, max_length=4)
    capability_requests: list[_CapabilityRequestPayload] = Field(default_factory=list, max_length=4)
    effect_proposals: list[_EffectProposalPayload] = Field(default_factory=list, max_length=4)
    checkpoint_reason: TutorCheckpointReason | None = None
    continuation_kind: TutorContinuationKind | None = None
    terminal_intent: Literal["completed"] | None = None

    @field_validator("public_message")
    @classmethod
    def _validate_public_message(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("public_message must not be blank")
        return value

    @field_validator("conversation_title")
    @classmethod
    def _validate_conversation_title(cls, value: str | None) -> str | None:
        if value is not None:
            _assert_safe_tutor_output(value)
        return value


class PrimaryTutorProviderGateway:
    """Use exactly the configured `OpenAICompatibleClient` provider and model."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: TutorJsonClient | None = None,
        max_output_tokens: int | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        resolved_max_output_tokens = self._settings.tutor_max_output_tokens
        if max_output_tokens is not None:
            resolved_max_output_tokens = max_output_tokens
        if resolved_max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        if self._settings.uses_deepseek_v4_flash_responses and (
            resolved_max_output_tokens > self._settings.tutor_deepseek_v4_flash_max_output_tokens
        ):
            raise ValueError("max_output_tokens exceeds the configured DeepSeek V4 Flash maximum")
        self._client = client
        self._max_output_tokens = resolved_max_output_tokens
        self._timeout_seconds = timeout_seconds

    def decide(
        self,
        *,
        run: TutorRunSnapshot,
        context: TutorContextSelection,
    ) -> TutorProviderResult:
        try:
            client = self._client if self._client is not None else OpenAICompatibleClient(self._settings)
            messages = _build_messages(run=run, context=context)
            for attempt in range(PRIMARY_PROVIDER_DECISION_ATTEMPTS):
                try:
                    response = client.complete_json(
                        messages,
                        temperature=None,
                        max_tokens=self._max_output_tokens,
                        timeout_seconds=self._timeout_seconds,
                    )
                    decision = parse_tutor_decision(response.content)
                    return TutorProviderResult(decision=decision, model=response.model or client.model)
                except TutorOutputSafetyError as exc:
                    diagnostic_code = _PROVIDER_OUTPUT_SAFETY_REJECTED
                    exception_type = type(exc).__name__
                    repairable = True
                except TutorDecisionValidationError as exc:
                    diagnostic_code = _PROVIDER_DECISION_INVALID
                    exception_type = type(exc).__name__
                    repairable = True
                except LLMInvalidResponseError as exc:
                    diagnostic_code = _provider_invalid_response_diagnostic_code(exc)
                    exception_type = type(exc).__name__
                    repairable = exc.kind in _REPAIRABLE_INVALID_RESPONSE_KINDS
                except (ValidationError, TypeError, ValueError) as exc:
                    diagnostic_code = _PROVIDER_DECISION_INVALID
                    exception_type = type(exc).__name__
                    repairable = True
                else:
                    continue

                logger.warning(
                    "Tutor primary model response was rejected (%s/%s): %s [%s]",
                    attempt + 1,
                    PRIMARY_PROVIDER_DECISION_ATTEMPTS,
                    exception_type,
                    diagnostic_code,
                )
                if not repairable or attempt + 1 == PRIMARY_PROVIDER_DECISION_ATTEMPTS:
                    return TutorProviderResult.model_unavailable(safe_code=diagnostic_code)
                messages.append({"role": "user", "content": _TUTOR_DECISION_REPAIR_MESSAGE})
            return TutorProviderResult.model_unavailable(safe_code=_PROVIDER_RESPONSE_INVALID)
        except LLMConfigurationError as exc:
            logger.warning("Tutor primary model configuration was unavailable: %s", type(exc).__name__)
            return TutorProviderResult.model_unavailable(safe_code=_PROVIDER_CONFIGURATION_UNAVAILABLE)
        except LLMCallError as exc:
            diagnostic_code = _provider_call_diagnostic_code(exc)
            logger.warning("Tutor primary model request was unavailable: %s", diagnostic_code)
            return TutorProviderResult.model_unavailable(safe_code=diagnostic_code)
        except Exception as exc:
            # A selected-provider adapter failure is never a reason to route to another provider.
            logger.warning("Tutor primary model adapter failed: %s", type(exc).__name__)
            return TutorProviderResult.model_unavailable(safe_code=_PROVIDER_ADAPTER_FAILED)


def _provider_invalid_response_diagnostic_code(exc: LLMInvalidResponseError) -> str:
    return {
        LLMInvalidResponseKind.ENVELOPE_INVALID: _PROVIDER_RESPONSE_ENVELOPE_INVALID,
        LLMInvalidResponseKind.CONTENT_MISSING: _PROVIDER_RESPONSE_CONTENT_MISSING,
        LLMInvalidResponseKind.CONTENT_NOT_JSON_OBJECT: _PROVIDER_RESPONSE_CONTENT_NOT_JSON,
        LLMInvalidResponseKind.RESPONSE_INCOMPLETE: _PROVIDER_RESPONSE_INCOMPLETE,
        LLMInvalidResponseKind.RESPONSE_FAILED: _PROVIDER_RESPONSE_FAILED,
    }.get(exc.kind, _PROVIDER_RESPONSE_INVALID)


def _provider_call_diagnostic_code(exc: LLMCallError) -> str:
    cause = exc.__cause__
    if isinstance(cause, urllib.error.HTTPError):
        status_code = int(cause.code)
        if status_code in {401, 403}:
            return _PROVIDER_AUTH_FAILED
        if status_code == 402:
            return _PROVIDER_QUOTA_UNAVAILABLE
        if status_code == 400:
            return _PROVIDER_REQUEST_REJECTED
        if status_code == 429:
            return _PROVIDER_RATE_LIMITED
        return _PROVIDER_HTTP_ERROR
    if _is_timeout_error(cause):
        return _PROVIDER_TIMEOUT
    return _PROVIDER_REQUEST_FAILED


def _is_timeout_error(exc: object | None) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    if isinstance(exc, urllib.error.URLError):
        return _is_timeout_error(exc.reason)
    return False


def parse_tutor_decision(payload: Mapping[str, object]) -> TutorDecision:
    """Validate one strict decision envelope and apply shared output guardrails."""
    try:
        envelope = _TutorDecisionEnvelope.model_validate(payload)
    except ValidationError as exc:
        raise TutorDecisionValidationError("Tutor decision failed strict schema validation") from exc

    if envelope.checkpoint_reason is TutorCheckpointReason.TERMINAL:
        raise TutorDecisionValidationError("Tutor decision cannot request a terminal checkpoint reason")
    if envelope.public_message is not None:
        _assert_safe_tutor_output(envelope.public_message)
    if envelope.conversation_title is not None:
        _assert_safe_tutor_output(envelope.conversation_title)
    if envelope.continuation_kind is not None:
        if envelope.checkpoint_reason is not TutorCheckpointReason.CAPABILITY_RESULT:
            raise TutorDecisionValidationError("Tutor continuation requires a capability-result checkpoint")
        if envelope.terminal_intent is not None:
            raise TutorDecisionValidationError("Tutor continuation cannot also be terminal")
    elif envelope.terminal_intent is None and not (
        envelope.skill_references or envelope.capability_requests or envelope.effect_proposals
    ):
        raise TutorDecisionValidationError("Tutor decision must be terminal or explicitly continued")

    skill_references = tuple(
        TutorSkillReference(skill_id=item.skill_id, version=item.version)
        for item in envelope.skill_references
    )
    capability_requests = tuple(
        TutorCapabilityRequest(
            request_id=item.request_id,
            capability_id=item.capability_id,
            arguments=payload_fields_from_mapping(item.arguments),
        )
        for item in envelope.capability_requests
    )
    effect_proposals = tuple(
        TutorEffectProposal(
            effect_id=item.effect_id,
            effect_type=item.effect_type,
            expected_input_revision=item.expected_input_revision,
            payload=payload_fields_from_mapping(item.payload),
        )
        for item in envelope.effect_proposals
    )
    _assert_payload_text_safe(capability_requests, effect_proposals)

    try:
        return TutorDecision(
            public_message=envelope.public_message,
            conversation_title=envelope.conversation_title,
            skill_references=skill_references,
            capability_requests=capability_requests,
            effect_proposals=effect_proposals,
            checkpoint_reason=envelope.checkpoint_reason,
            continuation_kind=envelope.continuation_kind,
            terminal_outcome=(TutorTerminalOutcome.COMPLETED if envelope.terminal_intent == "completed" else None),
        )
    except ValueError as exc:
        raise TutorDecisionValidationError("Tutor decision failed contract validation") from exc


def _build_messages(*, run: TutorRunSnapshot, context: TutorContextSelection) -> list[dict[str, str]]:
    system = (
        "You are the Aearn Tutor Harness decision boundary. Return one JSON object only. "
        "Always include a short, non-empty learner-facing public_message. "
        "Use exactly these keys: public_message, conversation_title, skill_references, "
        "capability_requests, effect_proposals, checkpoint_reason, continuation_kind, and terminal_intent. "
        "Use empty arrays when there are no skill, capability, or effect requests. "
        "conversation_title is either null or a concise learner-safe title no longer than 48 visible characters. "
        "A normal direct reply must set terminal_intent=completed and continuation_kind=null. "
        "A continuation_kind may be approval, capability_result, or external_result only when "
        "checkpoint_reason=capability_result and terminal_intent=null. Use null, not false, for absent optional values. "
        "Follow this exact complete shape (values may differ): "
        f"{_canonical_tutor_decision_example()} "
        "Include only the listed keys and values needed for this decision. "
        f"Teaching policy: {_TUTOR_TEACHING_POLICY}"
    )
    payload = {
        "input_revision": run.input_revision,
        "current_input": context.current_input.as_prompt_value() if context.current_input is not None else None,
        "context": context.as_prompt_context(),
        "context_metadata": context.checkpoint_metadata.as_dict(),
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
    ]


def _assert_payload_text_safe(
    capability_requests: tuple[TutorCapabilityRequest, ...],
    effect_proposals: tuple[TutorEffectProposal, ...],
) -> None:
    for request in capability_requests:
        _assert_safe_tutor_output(request.request_id)
        _assert_safe_tutor_output(request.capability_id)
        for field in request.arguments:
            _assert_safe_tutor_output(field.key)
            _assert_safe_tutor_output(field.value)
    for proposal in effect_proposals:
        _assert_safe_tutor_output(proposal.effect_id)
        _assert_safe_tutor_output(proposal.effect_type)
        for field in proposal.payload:
            _assert_safe_tutor_output(field.key)
            _assert_safe_tutor_output(field.value)
