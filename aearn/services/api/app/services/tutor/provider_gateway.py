"""Primary-only model gateway for the feature-disabled Tutor Harness."""
from __future__ import annotations

from app.agents.harness.contracts import TutorExecutionProfile
from app.services.llm.http_execution import LLMHTTPExecutionError
from app.services.llm.completion_policy import resolve_completion_stage_policy
from app.services.tutor.completion_execution import (
    CompletionNestedHTTPOutcome, CompletionTutorProviderResult, validate_completion_batch_settings,
)
from app.services.tutor.mvp_policy import MVPExecutionStopped, MVP_SOFT_CLOSE_AFTER, MVP_SOFT_CLOSE_HINT

import json
import logging
import socket
import urllib.error
from collections.abc import Callable, Mapping, Sequence
from typing import Literal, Protocol, TypedDict

from pydantic import ValidationError

from app.agents.harness.actions import is_current_verified_plan_draft_receipt
from app.agents.harness.capabilities import (
    LEARNING_PLAN_DRAFT_CAPABILITY_ID, LEARNING_PLAN_DRAFT_V110_DESCRIPTOR, CapabilitySchemaExporter,
    plan_draft_input_model,
)
from app.agents.harness.contracts import (
    TutorContextError,
    TutorTerminalOutcome,
    TutorCapabilityRequest,
    TutorContextSection,
    TutorContextSelection,
    TutorDecision,
    TutorEffectProposal,
    TutorProviderAttemptOutcome,
    TutorProviderAttemptReceipt,
    TutorProviderResult,
    TutorRunSnapshot,
    is_complete_selected_skill,
    payload_mapping_from_fields,
)
from app.agents.harness.provider_request import (
    TUTOR_TEACHING_POLICY,
    build_tutor_provider_messages,
)
from app.core.config import Settings, get_settings
from app.core.safe_diagnostics import log_safe_event
from app.core.teaching_safety import check_teaching_output
from app.services.llm.llm_client import (
    LLMCallError,
    LLMConfigurationError,
    LLMInvalidResponseError,
    LLMInvalidResponseKind,
    LLMJsonResponse,
    LLMVisibleOutputObserver,
    OpenAICompatibleClient,
    select_llm_protocol,
)
from app.services.llm.provider_diagnostics import (
    ProviderBodyCapture,
    ProviderDiagnosticMetadata,
    ProviderDiagnosticStore,
)
from app.services.tutor.ports import TutorLifecycleConflict
from app.services.tutor.provider_request_budget import assert_tutor_provider_request_budget
from app.services.tutor.validation_diagnostics import plan_domain_validation_issues, validation_log_fields
from app.services.learning.plan_drafting import decode_compact_modules, decode_compact_profile
from app.services.tutor.public_thinking_stream import (
    TutorProviderPublicTextProjector,
    TutorPublicThinkingSafetyError,
    TutorPublicThinkingSink,
    TutorPublicThinkingStreamError,
)
from app.services.tutor.decision_protocol import (
    TUTOR_PROVIDER_ITEMS_SCHEMA_NAME,
    TutorDecisionValidationError,
    TutorDecisionValidationIssue,
    build_tutor_replacement_message,
    parse_tutor_provider_items,
    tutor_provider_output_schema,
    tutor_provider_output_schema_hash,
    validation_diagnostic_code,
)


logger = logging.getLogger(__name__)


PRIMARY_PROVIDER_DECISION_ATTEMPTS = 2

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


class TutorOutputSafetyError(LLMInvalidResponseError):
    """A learner-visible Tutor output failed the shared teaching safety policy."""


class _CompletionStageArguments(TypedDict, total=False):
    completion_stage: str


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
        output_schema: Mapping[str, object] | None = None,
        schema_name: str | None = None,
        thinking_mode: Literal["enabled", "disabled"] | None = None,
        capture_provider_body: bool = False,
        visible_output_observer: LLMVisibleOutputObserver | None = None,
        completion_stage: str | None = None,
    ) -> LLMJsonResponse: ...


def _assert_safe_tutor_output(text: str) -> None:
    check = check_teaching_output(text)
    if check.blocked:
        raise TutorOutputSafetyError("Tutor output failed the teaching safety policy")


def _assert_selected_teaching_action(
    *, context: TutorContextSelection, decision: TutorDecision,
) -> None:
    if decision.teaching_step is not None:
        return
    # These are typed sources in this request, not provider-authored text.
    # CatalogContextLoader verifies selection for the current run/input revision
    # and published hashes before emitting the exact selected-Skill source id.
    teaching_scoped = any(item.section is TutorContextSection.TEACHING_SESSION for item in context.items)
    teaching_selected = any(
        item.section is TutorContextSection.SYSTEM
        and item.source_id == "catalog:selected:tutor.lesson-teaching@1.2.1"
        for item in context.items
    )
    if teaching_scoped and teaching_selected:
        raise TutorDecisionValidationError(
            "Tutor selected teaching Skill requires a teaching step",
            issues=(TutorDecisionValidationIssue(path="action.type", category="teaching_step_required"),),
        )


def _is_verified_plan_completion(*, run: TutorRunSnapshot, context: TutorContextSelection) -> bool:
    # The receipt loader scopes these server-owned records to user_id/run_id.
    # It can also include older revisions; only the current revision closes this request.
    return any(
        item.section is TutorContextSection.ACTION_RECEIPTS
        and item.source_id.startswith("action-receipt:")
        and is_current_verified_plan_draft_receipt(
            item.content, input_revision=run.input_revision,
        )
        for item in context.items
    )


def _assert_plan_draft_not_repeated(
    *, run: TutorRunSnapshot, context: TutorContextSelection, action: object,
) -> None:
    if (_is_verified_plan_completion(run=run, context=context) and isinstance(action, Mapping)
        and action.get("type") == "request_capability"
        and action.get("capability_id") == LEARNING_PLAN_DRAFT_CAPABILITY_ID
    ):
        raise TutorDecisionValidationError(
            "Tutor attempted a completed learning-plan draft action",
            issues=(TutorDecisionValidationIssue(
                path="action.type", category="plan_draft_already_verified",
            ),),
        )


def _assert_plan_domain_shape(decision: TutorDecision) -> None:
    """Reject pure JSON/domain-shape failures before paid material review or writes."""
    for request in decision.capability_requests:
        if request.capability_id != LEARNING_PLAN_DRAFT_CAPABILITY_ID:
            continue
        try:
            candidate = plan_draft_input_model(request.capability_version).model_validate(
                payload_mapping_from_fields(request.arguments))
        except ValidationError as exc:
            raise TutorDecisionValidationError("Plan capability shape is invalid", issues=(
                TutorDecisionValidationIssue(path="action.arguments", category="plan_domain_invalid"),
            )) from exc
        parts = (("profile_json", candidate.profile_json),
                 *((f"module_{index}", value) for index, value in enumerate(candidate.module_values(), 1)))
        for key, value in parts:
            try:
                if key == "profile_json":
                    decode_compact_profile(value)
                else:
                    decode_compact_modules((value,))
            except ValidationError as exc:
                raise TutorDecisionValidationError("Plan domain shape is invalid",
                    issues=plan_domain_validation_issues(exc, argument_key=key)) from exc
            except ValueError as exc:
                raise TutorDecisionValidationError("Plan argument is not a JSON object", issues=(
                    TutorDecisionValidationIssue(path=f"action.arguments.{key}", category="plan_json_invalid"),
                )) from exc


def _selected_plan_draft_version(context: TutorContextSelection) -> str:
    selected = any(
        item.section is TutorContextSection.SYSTEM
        and item.source_id == "catalog:selected:tutor.learning-plan-draft@1.1.0"
        and is_complete_selected_skill(item.source_id, item.content)
        for item in context.items
    )
    if selected:
        for item in context.items:
            if (item.section is TutorContextSection.CAPABILITY_SCHEMAS
                    and item.source_id == "catalog:capability:learning.plan.draft@1.1.0"):
                try:
                    if json.loads(item.content) == CapabilitySchemaExporter.export(LEARNING_PLAN_DRAFT_V110_DESCRIPTOR):
                        return "1.1.0"
                except (TypeError, ValueError):
                    pass
    return "1.0.0"


class PrimaryTutorProviderGateway:
    """Use exactly the configured provider and assemble control fields server-side."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: TutorJsonClient | None = None,
        max_output_tokens: int | None = None,
        timeout_seconds: float | None = None,
        decision_validator: Callable[[TutorRunSnapshot, TutorContextSelection, TutorDecision, int], str | None] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        resolved_max_output_tokens = self._settings.tutor_decision_max_output_tokens
        if max_output_tokens is not None:
            resolved_max_output_tokens = max_output_tokens
        if resolved_max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        if self._settings.uses_deepseek_v4_flash_responses and (
            resolved_max_output_tokens
            > self._settings.tutor_deepseek_v4_flash_max_output_tokens
        ):
            raise ValueError("max_output_tokens exceeds the configured DeepSeek Flash maximum")
        self._client = client
        self._max_output_tokens = resolved_max_output_tokens
        self._timeout_seconds = timeout_seconds
        self._output_schema = tutor_provider_output_schema()
        self._output_schema_hash = tutor_provider_output_schema_hash()
        self._decision_validator = decision_validator

    def with_decision_validator(
        self, validator: Callable[[TutorRunSnapshot, TutorContextSelection, TutorDecision, int], str | None],
    ) -> PrimaryTutorProviderGateway:
        """Bind an internal validator without changing the ordinary gateway."""
        if self._decision_validator is not None:
            raise ValueError("decision validator already bound")
        return PrimaryTutorProviderGateway(
            settings=self._settings, client=self._client,
            max_output_tokens=self._max_output_tokens, timeout_seconds=self._timeout_seconds,
            decision_validator=validator,
        )

    def decide(
        self,
        *,
        run: TutorRunSnapshot,
        context: TutorContextSelection,
        thinking_sink: TutorPublicThinkingSink | None = None,
    ) -> TutorProviderResult:
        attempts: list[TutorProviderAttemptReceipt] = []
        if run.policy.execution_profile is TutorExecutionProfile.COMPLETION_DRIVEN_V1:
            if not self._settings.tutor_completion_driven_enabled:
                return TutorProviderResult.model_unavailable(safe_code='completion_feature_disabled')
            validate_completion_batch_settings(self._settings)
        try:
            completion_policy = (
                resolve_completion_stage_policy(self._settings, 'tutor_decision')
                if run.policy.execution_profile is TutorExecutionProfile.COMPLETION_DRIVEN_V1 else None
            )
            max_output_tokens = completion_policy.max_output_tokens if completion_policy else self._max_output_tokens
            timeout_seconds = completion_policy.timeout_seconds if completion_policy else self._timeout_seconds
            completion_arguments: _CompletionStageArguments = (
                {"completion_stage": "tutor_decision"} if completion_policy is not None else {}
            )
            client = (
                self._client
                if self._client is not None
                else _build_default_client(self._settings)
            )
            messages = _build_messages(run=run, context=context)
            protocol = select_llm_protocol(self._settings).value
            provider_type = self._settings.llm_provider_type
            plan_completion = _is_verified_plan_completion(run=run, context=context)
            plan_draft_version = _selected_plan_draft_version(context)
            supports_visible_stream = (
                thinking_sink is not None
                and protocol in {"responses", "deepseek_responses"}
                and isinstance(client, OpenAICompatibleClient)
            )
        except LLMConfigurationError as exc:
            logger.warning(
                "Tutor primary model configuration was unavailable: %s",
                type(exc).__name__,
            )
            return TutorProviderResult.model_unavailable(
                safe_code=_PROVIDER_CONFIGURATION_UNAVAILABLE
            )
        except Exception as exc:
            logger.warning(
                "Tutor primary model adapter failed before invocation: %s",
                type(exc).__name__,
            )
            return TutorProviderResult.model_unavailable(
                safe_code=_PROVIDER_ADAPTER_FAILED
            )

        replacement_issues: tuple[TutorDecisionValidationIssue, ...] = ()
        rejected_planning = False
        for attempt_index in range(1, PRIMARY_PROVIDER_DECISION_ATTEMPTS + 1):
            response: LLMJsonResponse | None = None
            rejected_capture: ProviderBodyCapture | None = None
            projector: TutorProviderPublicTextProjector | None = None
            if supports_visible_stream and thinking_sink is not None:
                thinking_sink.begin_attempt(attempt_index)
                projector = TutorProviderPublicTextProjector(
                    attempt_index=attempt_index,
                    sink=thinking_sink,
                )
            if attempt_index > 1:
                messages = _build_messages(run=run, context=context)
                messages.append(
                    {
                        "role": "user",
                        "content": build_tutor_replacement_message(
                            replacement_issues,
                            teaching_policy=TUTOR_TEACHING_POLICY,
                            planning_capability_active=rejected_planning,
                            plan_draft_version=plan_draft_version,
                        ),
                    }
                )
            policy = run.policy.context_budget_policy
            if policy is None:
                from app.agents.harness.context_budget import resolve_tutor_provider_context_capability
                capability = resolve_tutor_provider_context_capability(self._settings)
            else:
                capability = policy.capability
            if completion_policy is not None and completion_policy.context_capability is not None:
                capability = completion_policy.context_capability
            try:
                assert_tutor_provider_request_budget(messages, capability=capability)
            except TutorContextError as exc:
                if projector is not None and thinking_sink is not None:
                    thinking_sink.discard_attempt(attempt_index)
                return TutorProviderResult(
                    decision=None, terminal_outcome=TutorTerminalOutcome.FAILED,
                    safe_code=exc.safe_code, attempts=tuple(attempts),
                )
            try:
                thinking_mode: Literal["enabled", "disabled"] | None = (
                    "disabled"
                    if (
                        provider_type == "deepseek"
                        and (plan_completion or (
                            attempt_index > 1
                            and self._settings.tutor_deepseek_repair_thinking_disabled
                        ))
                    )
                    else None
                )
                if projector is None:
                    response = client.complete_json(
                        messages,
                        temperature=None,
                        max_tokens=max_output_tokens,
                        timeout_seconds=timeout_seconds,
                        output_schema=self._output_schema,
                        schema_name=TUTOR_PROVIDER_ITEMS_SCHEMA_NAME,
                        thinking_mode=thinking_mode,
                        capture_provider_body=True,
                        **completion_arguments,
                    )
                else:
                    response = client.complete_json(
                        messages,
                        temperature=None,
                        max_tokens=max_output_tokens,
                        timeout_seconds=timeout_seconds,
                        output_schema=self._output_schema,
                        schema_name=TUTOR_PROVIDER_ITEMS_SCHEMA_NAME,
                        thinking_mode=thinking_mode,
                        capture_provider_body=True,
                        visible_output_observer=projector,
                        **completion_arguments,
                    )
                _assert_raw_provider_text_safe(response.content)
                _assert_plan_draft_not_repeated(run=run, context=context, action=response.content.get("action"))
                decision = parse_tutor_provider_items(response.content, run=run, plan_draft_version=plan_draft_version)
                _assert_decision_text_safe(decision)
                _assert_selected_teaching_action(context=context, decision=decision)
                _assert_plan_domain_shape(decision)
                if projector is not None and thinking_sink is not None:
                    raw_message = response.content.get("message")
                    raw_thinking = (
                        raw_message.get("public_thinking_text")
                        if isinstance(raw_message, Mapping)
                        else None
                    )
                    if not isinstance(raw_thinking, str) or projector.text != raw_thinking:
                        raise TutorDecisionValidationError(
                            "Tutor streamed public thinking did not match the final provider object",
                            issues=(
                                TutorDecisionValidationIssue(
                                    path="message.public_thinking_text",
                                    category="stream_mismatch",
                                ),
                            ),
                        )
                if self._decision_validator is not None:
                    material_issue = self._decision_validator(run, context, decision, attempt_index)
                    if material_issue is not None:
                        raise TutorDecisionValidationError(
                            "Internal planning output failed material consistency",
                            issues=(TutorDecisionValidationIssue(
                                path="action.arguments.profile_json", category=material_issue,
                            ),),
                        )
                if projector is not None and thinking_sink is not None:
                    # ``complete`` is the public validation barrier, not merely the
                    # provider transport EOF. Invalid attempts must go straight from
                    # provisional append events to discard without becoming visible.
                    thinking_sink.complete_attempt(attempt_index)
            except LLMConfigurationError as exc:
                if projector is not None and thinking_sink is not None:
                    thinking_sink.discard_attempt(attempt_index)
                logger.warning(
                    "Tutor primary model configuration was unavailable: %s",
                    type(exc).__name__,
                )
                return TutorProviderResult.model_unavailable(
                    safe_code=_PROVIDER_CONFIGURATION_UNAVAILABLE,
                    attempts=tuple(attempts),
                )
            except LLMHTTPExecutionError as exc:
                if projector is not None and thinking_sink is not None:
                    thinking_sink.discard_attempt(attempt_index)
                prefix = 'completion' if completion_policy is not None else 'mvp'
                code = prefix + ("_http_unknown_" if exc.outcome_unknown else "_http_") + exc.reason
                if completion_policy is not None and response is not None:
                    # The Tutor HTTP returned before its material validator sent
                    # another HTTP. Keep those two origins separate: the original
                    # Tutor receipt uses response usage/model, never semantic usage.
                    _commit_provider_diagnostic(response.diagnostic_capture, run=run, attempt_index=attempt_index,
                        provider_type=provider_type, protocol=protocol, model=response.model or client.model,
                        diagnostic_code=code, contract_hash=self._output_schema_hash)
                    attempts.append(TutorProviderAttemptReceipt(
                        attempt_index=attempt_index, outcome=TutorProviderAttemptOutcome.TERMINAL_REJECTED,
                        provider_type=provider_type, protocol=protocol, model=response.model or client.model,
                        usage=response.usage, diagnostic_code=code,
                    ))
                    if exc.outcome_unknown:
                        binding_hash = getattr(exc, 'request_binding_hash', None)
                        nested = CompletionNestedHTTPOutcome(
                            stage='material_semantic_review',
                            request_binding_hash=binding_hash if isinstance(binding_hash, str) else None,
                            current_scope_http_attempts=exc.physical_attempts,
                            from_dispatched_receipt=bool(getattr(exc, 'from_dispatched_receipt', False)),
                            model=exc.model, usage=exc.usage, response_diagnostics=exc.response_diagnostics,
                        )
                        return CompletionTutorProviderResult(decision=None,
                            terminal_outcome=TutorTerminalOutcome.MODEL_UNAVAILABLE,
                            safe_code=code, attempts=tuple(attempts), nested_http_outcomes=(nested,))
                    return TutorProviderResult.model_unavailable(safe_code=code, attempts=tuple(attempts))
                _commit_provider_diagnostic(exc.diagnostic_capture, run=run, attempt_index=attempt_index,
                    provider_type=provider_type, protocol=protocol, model=exc.model or client.model,
                    diagnostic_code=code, contract_hash=self._output_schema_hash)
                if exc.outcome_unknown or exc.reason in {"pre_send_retries_exhausted", "http_error"}:
                    attempts.append(TutorProviderAttemptReceipt(attempt_index=attempt_index,
                        outcome=(TutorProviderAttemptOutcome.TERMINAL_REJECTED if exc.usage is not None
                                 else TutorProviderAttemptOutcome.TRANSPORT_FAILED), provider_type=provider_type,
                        protocol=protocol, model=exc.model or client.model, usage=exc.usage, diagnostic_code=code))
                outcome = (TutorTerminalOutcome.BUDGET_EXHAUSTED if exc.reason == "physical_attempts_exhausted"
                           else TutorTerminalOutcome.MODEL_UNAVAILABLE)
                return TutorProviderResult(decision=None, terminal_outcome=outcome,
                    safe_code=code, attempts=tuple(attempts))
            except LLMCallError as exc:
                if projector is not None and thinking_sink is not None:
                    thinking_sink.discard_attempt(attempt_index)
                diagnostic_code = _provider_call_diagnostic_code(exc)
                _commit_provider_diagnostic(
                    exc.diagnostic_capture,
                    run=run,
                    attempt_index=attempt_index,
                    provider_type=provider_type,
                    protocol=protocol,
                    model=client.model,
                    diagnostic_code=diagnostic_code,
                    contract_hash=self._output_schema_hash,
                )
                attempts.append(
                    TutorProviderAttemptReceipt(
                        attempt_index=attempt_index,
                        outcome=TutorProviderAttemptOutcome.TRANSPORT_FAILED,
                        provider_type=provider_type,
                        protocol=protocol,
                        model=client.model,
                        diagnostic_code=diagnostic_code,
                    )
                )
                logger.warning(
                    "Tutor primary model request was unavailable: %s", diagnostic_code
                )
                return TutorProviderResult.model_unavailable(
                    safe_code=diagnostic_code,
                    attempts=tuple(attempts),
                )
            except TutorPublicThinkingSafetyError as exc:
                diagnostic_code = _PROVIDER_OUTPUT_SAFETY_REJECTED
                exception_type = type(exc).__name__
                repairable = True
                replacement_issues = (
                    TutorDecisionValidationIssue(
                        path="message.public_thinking_text",
                        category="unsafe_output",
                    ),
                )
                rejected_capture = response.diagnostic_capture if response is not None else None
                usage = response.usage if response is not None else None
                model = (response.model if response is not None else None) or client.model
            except TutorPublicThinkingStreamError as exc:
                diagnostic_code = _PROVIDER_DECISION_INVALID
                exception_type = type(exc).__name__
                repairable = True
                replacement_issues = (
                    TutorDecisionValidationIssue(
                        path="message.public_thinking_text",
                        category="invalid_stream",
                    ),
                )
                rejected_capture = response.diagnostic_capture if response is not None else None
                usage = response.usage if response is not None else None
                model = (response.model if response is not None else None) or client.model
            except TutorOutputSafetyError as exc:
                diagnostic_code = _PROVIDER_OUTPUT_SAFETY_REJECTED
                exception_type = type(exc).__name__
                repairable = True
                replacement_issues = (
                    TutorDecisionValidationIssue(
                        path="message",
                        category="unsafe_output",
                    ),
                )
                rejected_capture = (
                    response.diagnostic_capture
                    if response is not None
                    else exc.diagnostic_capture
                )
                usage = response.usage if response is not None else exc.usage
                model = (response.model if response is not None else exc.model) or client.model
            except TutorDecisionValidationError as exc:
                diagnostic_code = validation_diagnostic_code(exc.issues)
                exception_type = type(exc).__name__
                repairable = not any(issue.category.startswith("material_review_uncertain")
                                     for issue in exc.issues)
                replacement_issues = exc.issues
                rejected_capture = (
                    response.diagnostic_capture
                    if response is not None
                    else exc.diagnostic_capture
                )
                usage = response.usage if response is not None else exc.usage
                model = (response.model if response is not None else exc.model) or client.model
            except LLMInvalidResponseError as exc:
                diagnostic_code = _provider_invalid_response_diagnostic_code(exc)
                exception_type = type(exc).__name__
                repairable = exc.kind in _REPAIRABLE_INVALID_RESPONSE_KINDS
                replacement_issues = (
                    TutorDecisionValidationIssue(
                        path="root",
                        category=exc.kind.value,
                    ),
                )
                rejected_capture = (
                    response.diagnostic_capture
                    if response is not None
                    else exc.diagnostic_capture
                )
                usage = response.usage if response is not None else exc.usage
                model = (response.model if response is not None else exc.model) or client.model
            except (TypeError, ValueError) as exc:
                diagnostic_code = _PROVIDER_DECISION_INVALID
                exception_type = type(exc).__name__
                repairable = True
                replacement_issues = (
                    TutorDecisionValidationIssue(
                        path="root",
                        category="invalid_contract",
                    ),
                )
                rejected_capture = (
                    response.diagnostic_capture if response is not None else None
                )
                usage = response.usage if response is not None else None
                model = (response.model if response is not None else None) or client.model
            except TutorLifecycleConflict:
                raise
            except MVPExecutionStopped as exc:
                return TutorProviderResult(decision=None, terminal_outcome=exc.outcome,
                    safe_code=exc.safe_code, attempts=tuple(attempts))
            except Exception as exc:
                if projector is not None and thinking_sink is not None:
                    thinking_sink.discard_attempt(attempt_index)
                diagnostic_code = _PROVIDER_ADAPTER_FAILED
                if response is not None:
                    _commit_provider_diagnostic(
                        response.diagnostic_capture,
                        run=run,
                        attempt_index=attempt_index,
                        provider_type=provider_type,
                        protocol=protocol,
                        model=response.model or client.model,
                        diagnostic_code=diagnostic_code,
                        contract_hash=self._output_schema_hash,
                    )
                    attempts.append(
                        TutorProviderAttemptReceipt(
                            attempt_index=attempt_index,
                            outcome=TutorProviderAttemptOutcome.TERMINAL_REJECTED,
                            provider_type=provider_type,
                            protocol=protocol,
                            model=response.model or client.model,
                            usage=response.usage,
                            diagnostic_code=diagnostic_code,
                        )
                    )
                logger.warning(
                    "Tutor primary model adapter failed: %s", type(exc).__name__
                )
                return TutorProviderResult.model_unavailable(
                    safe_code=diagnostic_code,
                    attempts=tuple(attempts),
                )
            else:
                model = response.model or client.model
                if response.diagnostic_capture is not None:
                    response.diagnostic_capture.discard()
                attempts.append(
                    TutorProviderAttemptReceipt(
                        attempt_index=attempt_index,
                        outcome=TutorProviderAttemptOutcome.ACCEPTED,
                        provider_type=provider_type,
                        protocol=protocol,
                        model=model,
                        usage=response.usage,
                    )
                )
                return TutorProviderResult(
                    decision=decision,
                    model=model,
                    attempts=tuple(attempts),
                )

            if projector is not None and thinking_sink is not None:
                thinking_sink.discard_attempt(attempt_index)
            artifact_id = _commit_provider_diagnostic(
                rejected_capture,
                run=run,
                attempt_index=attempt_index,
                provider_type=provider_type,
                protocol=protocol,
                model=model,
                diagnostic_code=diagnostic_code,
                contract_hash=self._output_schema_hash,
            )
            attempts.append(
                TutorProviderAttemptReceipt(
                    attempt_index=attempt_index,
                    outcome=(
                        TutorProviderAttemptOutcome.REPAIRABLE_REJECTED
                        if repairable
                        else TutorProviderAttemptOutcome.TERMINAL_REJECTED
                    ),
                    provider_type=provider_type,
                    protocol=protocol,
                    model=model,
                    usage=usage,
                    diagnostic_code=diagnostic_code,
                )
            )
            rejected_action = response.content.get("action") if response is not None else None
            rejected_planning = (
                isinstance(rejected_action, Mapping)
                and rejected_action.get("type") == "request_capability"
                and rejected_action.get("capability_id") == "learning.plan.draft"
                and not any(
                    issue.category == "plan_draft_already_verified"
                    for issue in replacement_issues
                )
                and any(item.section is TutorContextSection.CAPABILITY_SCHEMAS
                        and "learning.plan.draft" in item.content for item in context.items)
            )
            for issue in replacement_issues[:8]:
                details = validation_log_fields(issue)
                log_safe_event(
                    logger, "tutor_provider_validation_issue",
                    run_id=run.run_id, input_revision=run.input_revision,
                    decision_iteration=run.model_call_count + 1,
                    attempt=attempt_index, code=diagnostic_code,
                    model=self._settings.llm_model or "unknown",
                    provider_type=provider_type, protocol=protocol,
                    artifact_id=artifact_id,
                    max_attempts=PRIMARY_PROVIDER_DECISION_ATTEMPTS,
                    repair_attempt=attempt_index - 1,
                    retry_allowed=repairable and attempt_index < PRIMARY_PROVIDER_DECISION_ATTEMPTS,
                    remaining_repair_attempts=(
                        PRIMARY_PROVIDER_DECISION_ATTEMPTS - attempt_index if repairable else 0
                    ),
                    stage=issue.category,
                    field_path=details.get("field_path"),
                    expected_values=details.get("expected_values"),
                    expected_rule=details.get("expected_rule"),
                    expected_type=details.get("expected_type"),
                    expected_types=details.get("expected_types"),
                    observed_type=details.get("observed_type"),
                    string_length=details.get("string_length"),
                    serialized_length=details.get("serialized_length"),
                    list_count=details.get("list_count"),
                    argument_key=details.get("argument_key"),
                )
            logger.warning(
                "Tutor primary model response was rejected (%s/%s): %s [%s] "
                "contract=%s",
                attempt_index,
                PRIMARY_PROVIDER_DECISION_ATTEMPTS,
                exception_type,
                diagnostic_code,
                self._output_schema_hash[:12],
            )
            if not repairable or attempt_index == PRIMARY_PROVIDER_DECISION_ATTEMPTS:
                return TutorProviderResult.model_unavailable(
                    safe_code=diagnostic_code,
                    attempts=tuple(attempts),
                )

        return TutorProviderResult.model_unavailable(
            safe_code=_PROVIDER_RESPONSE_INVALID,
            attempts=tuple(attempts),
        )


def _build_default_client(settings: Settings) -> OpenAICompatibleClient:
    try:
        diagnostic_store = ProviderDiagnosticStore.from_settings(settings)
    except ValueError as exc:
        raise LLMConfigurationError(
            "Tutor provider diagnostic configuration is invalid"
        ) from exc
    return OpenAICompatibleClient(
        settings,
        diagnostic_store=diagnostic_store,
    )


class _DiagnosticAttemptIdentity(TypedDict):
    run_id: str
    input_revision: int
    decision_iteration: int
    attempt: int
    code: str


def _commit_provider_diagnostic(
    capture: ProviderBodyCapture | None,
    *,
    run: TutorRunSnapshot,
    attempt_index: int,
    provider_type: str,
    protocol: str,
    model: str,
    diagnostic_code: str,
    contract_hash: str,
) -> str | None:
    identity: _DiagnosticAttemptIdentity = {
        "run_id": run.run_id, "input_revision": run.input_revision,
        "decision_iteration": run.model_call_count + 1, "attempt": attempt_index,
        "code": diagnostic_code,
    }
    if capture is None:
        log_safe_event(logger, "tutor_provider_diagnostic_capture", capture_state="not_captured", **identity)
        return None
    try:
        artifact = capture.commit(
            ProviderDiagnosticMetadata(
                run_id=run.run_id,
                input_revision=run.input_revision,
                decision_iteration=run.model_call_count + 1,
                attempt_index=attempt_index,
                provider_type=provider_type,
                protocol=protocol,
                model=model,
                diagnostic_code=diagnostic_code,
                contract_hash=contract_hash,
            )
        )
    except Exception as exc:
        log_safe_event(
            logger, "tutor_provider_diagnostic_capture",
            capture_state="failed", exception=exc, **identity,
        )
        return None
    log_safe_event(
        logger, "tutor_provider_diagnostic_capture",
        capture_state="saved" if artifact else "empty",
        artifact_id=artifact.artifact_id if artifact else None,
        captured_bytes=artifact.captured_bytes if artifact else 0,
        truncated=artifact.truncated if artifact else False,
        **identity,
    )
    return artifact.artifact_id if artifact else None


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


def parse_tutor_decision(
    payload: Mapping[str, object],
    *,
    run: TutorRunSnapshot,
) -> TutorDecision:
    """Compatibility name for the typed provider protocol parser."""

    _assert_raw_provider_text_safe(payload)
    decision = parse_tutor_provider_items(payload, run=run)
    _assert_decision_text_safe(decision)
    return decision


def _build_messages(*, run: TutorRunSnapshot, context: TutorContextSelection) -> list[dict[str, str]]:
    """Compatibility alias for tests and evals using the shared serializer."""

    messages = build_tutor_provider_messages(run=run, context=context)
    if run.policy.execution_profile is TutorExecutionProfile.MVP_TEACHING_V1 and run.model_call_count >= MVP_SOFT_CLOSE_AFTER:
        messages.append({"role": "system", "content": MVP_SOFT_CLOSE_HINT})
    return messages


def _assert_raw_provider_text_safe(payload: Mapping[str, object]) -> None:
    message = payload.get("message")
    if isinstance(message, Mapping):
        for key in ("text", "conversation_title"):
            value = message.get(key)
            if isinstance(value, str):
                _assert_safe_tutor_output(value)
        public_thinking_text = message.get("public_thinking_text")
        if isinstance(public_thinking_text, str):
            _assert_safe_tutor_output(public_thinking_text)
    action = payload.get("action")
    if not isinstance(action, Mapping):
        return
    for key in ("skill_id", "version", "capability_id", "effect_type"):
        value = action.get(key)
        if isinstance(value, str):
            _assert_safe_tutor_output(value)
    for key in ("arguments", "payload"):
        fields = action.get(key)
        if not isinstance(fields, Sequence) or isinstance(fields, (str, bytes)):
            continue
        for field in fields:
            if not isinstance(field, Mapping):
                continue
            if "value" in field:
                _assert_safe_tutor_output(
                    json.dumps(field["value"], ensure_ascii=False, sort_keys=True)
                )


def _assert_decision_text_safe(decision: TutorDecision) -> None:
    if decision.public_message is not None:
        _assert_safe_tutor_output(decision.public_message)
    if decision.public_thinking_text:
        _assert_safe_tutor_output(decision.public_thinking_text)
    if decision.conversation_title is not None:
        _assert_safe_tutor_output(decision.conversation_title)
    _assert_payload_text_safe(decision.capability_requests, decision.effect_proposals)


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
