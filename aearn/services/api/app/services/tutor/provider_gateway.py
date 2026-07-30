"""Primary-only model gateway for the feature-disabled Tutor Harness."""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.agents.harness.contracts import (
    MAX_TUTOR_PAYLOAD_FIELDS,
    MAX_TUTOR_PUBLIC_MESSAGE_LENGTH,
    TutorCapabilityRequest,
    TutorCheckpointReason,
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
    LLMJsonResponse,
    OpenAICompatibleClient,
)


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
        raise LLMInvalidResponseError(f"Teaching output guardrail blocked {check.category}")


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
    skill_references: list[_SkillReferencePayload] = Field(default_factory=list, max_length=4)
    capability_requests: list[_CapabilityRequestPayload] = Field(default_factory=list, max_length=4)
    effect_proposals: list[_EffectProposalPayload] = Field(default_factory=list, max_length=4)
    checkpoint_reason: TutorCheckpointReason | None = None
    terminal_intent: Literal["completed"] | None = None

    @field_validator("public_message")
    @classmethod
    def _validate_public_message(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("public_message must not be blank")
        return value


class PrimaryTutorProviderGateway:
    """Use exactly the configured `OpenAICompatibleClient` provider and model."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: TutorJsonClient | None = None,
        max_output_tokens: int = 1200,
        timeout_seconds: float | None = None,
    ) -> None:
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        self._settings = settings or get_settings()
        self._client = client
        self._max_output_tokens = max_output_tokens
        self._timeout_seconds = timeout_seconds

    def decide(
        self,
        *,
        run: TutorRunSnapshot,
        context: TutorContextSelection,
    ) -> TutorProviderResult:
        try:
            client = self._client if self._client is not None else OpenAICompatibleClient(self._settings)
            response = client.complete_json(
                _build_messages(run=run, context=context),
                temperature=None,
                max_tokens=self._max_output_tokens,
                timeout_seconds=self._timeout_seconds,
            )
            decision = parse_tutor_decision(response.content)
            return TutorProviderResult(decision=decision, model=response.model or client.model)
        except (
            LLMCallError,
            LLMConfigurationError,
            LLMInvalidResponseError,
            ValidationError,
            TypeError,
            ValueError,
        ):
            return TutorProviderResult.model_unavailable()
        except Exception:
            # A selected-provider adapter failure is never a reason to route to another provider.
            return TutorProviderResult.model_unavailable()


def parse_tutor_decision(payload: Mapping[str, object]) -> TutorDecision:
    """Validate one strict decision envelope and apply shared output guardrails."""
    try:
        envelope = _TutorDecisionEnvelope.model_validate(payload)
    except ValidationError as exc:
        raise LLMInvalidResponseError("Tutor decision failed strict schema validation") from exc

    if envelope.checkpoint_reason is TutorCheckpointReason.TERMINAL:
        raise LLMInvalidResponseError("Tutor decision cannot request a terminal checkpoint reason")
    if envelope.public_message is not None:
        _assert_safe_tutor_output(envelope.public_message)

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

    return TutorDecision(
        public_message=envelope.public_message,
        skill_references=skill_references,
        capability_requests=capability_requests,
        effect_proposals=effect_proposals,
        checkpoint_reason=envelope.checkpoint_reason,
        terminal_outcome=(TutorTerminalOutcome.COMPLETED if envelope.terminal_intent == "completed" else None),
    )


def _build_messages(*, run: TutorRunSnapshot, context: TutorContextSelection) -> list[dict[str, str]]:
    system = (
        "You are the Aearn Tutor Harness decision boundary. Return one JSON object only. "
        "Allowed keys are public_message, skill_references, capability_requests, "
        "effect_proposals, checkpoint_reason, and terminal_intent. Do not include "
        "reasoning, diagnostics, provider data, prompts, secrets, or unknown keys."
    )
    payload = {
        "input_revision": run.input_revision,
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
