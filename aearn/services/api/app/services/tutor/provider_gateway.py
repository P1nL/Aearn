"""Primary-only model gateway for the feature-disabled Tutor Harness."""
from __future__ import annotations

import json
import logging
import socket
import urllib.error
from collections.abc import Mapping, Sequence
from typing import Literal, Protocol, TypedDict

from app.agents.harness.contracts import (
    TutorCapabilityRequest,
    TutorContextSection,
    TutorContextSelection,
    TutorDecision,
    TutorEffectProposal,
    TutorProviderAttemptOutcome,
    TutorProviderAttemptReceipt,
    TutorProviderResult,
    TutorRunSnapshot,
)
from app.agents.harness.provider_request import (
    TUTOR_TEACHING_POLICY,
    build_tutor_provider_messages,
)
from app.core.config import Settings, get_settings
from app.core.safe_diagnostics import log_safe_event
from app.core.teaching_safety import check_teaching_output
from app.services.learning.teaching_contracts import teaching_focus_resolution_error
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
from app.services.tutor.validation_diagnostics import validation_log_fields
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


def _assert_teaching_focus_authority(
    *, context: TutorContextSelection, decision: TutorDecision,
) -> None:
    """Repair provider choices against this request's typed server authority only."""
    step = decision.teaching_step
    if step is None:
        return
    sources = [item for item in context.items if item.section is TutorContextSection.TEACHING_SESSION]
    if not sources:
        return  # The final Gate separately rejects an unexpected teaching scope.

    def invalid_authority() -> TutorDecisionValidationError:
        return TutorDecisionValidationError(
            "Tutor teaching focus authority is invalid",
            issues=(TutorDecisionValidationIssue(
                path="action.focus_resolution", category="focus_authority_invalid",
            ),),
        )

    if len(sources) != 1 or not sources[0].source_id.startswith("teaching-session:"):
        raise invalid_authority()
    try:
        authority = json.loads(sources[0].content)
    except (ValueError, TypeError) as exc:
        raise invalid_authority() from exc
    if not isinstance(authority, dict):
        raise invalid_authority()
    objective = authority.get("objective")
    active = authority.get("active_focus")
    candidate = authority.get("candidate_focus_id")
    parents = authority.get("suspended_focuses", [])
    if not isinstance(objective, dict) or not isinstance(parents, list):
        raise invalid_authority()
    if active is not None and not isinstance(active, dict):
        raise invalid_authority()
    objective_id = objective.get("objective_id")
    active_id = active.get("focus_id") if isinstance(active, dict) else ""
    if not all(isinstance(value, str) and value for value in (objective_id, candidate)):
        raise invalid_authority()
    if not isinstance(active_id, str) or (active is not None and not active_id):
        raise invalid_authority()
    parent_ids: list[str] = []
    for parent in parents:
        if not isinstance(parent, dict):
            raise invalid_authority()
        parent_id = parent.get("focus_id")
        if not isinstance(parent_id, str) or not parent_id:
            raise invalid_authority()
        parent_ids.append(parent_id)
    # Explicit narrowing keeps malformed server facts out of the shared policy.
    assert isinstance(objective_id, str) and isinstance(active_id, str) and isinstance(candidate, str)
    error = teaching_focus_resolution_error(
        resolution=step.focus_resolution, focus_id=step.focus_id,
        objective_id=objective_id, active_focus_id=active_id,
        candidate_focus_id=candidate, suspended_focus_ids=parent_ids,
    )
    if error is not None:
        raise TutorDecisionValidationError(
            "Tutor teaching focus choice violates current authority",
            issues=(TutorDecisionValidationIssue(
                path="action.focus_resolution", category="focus_resolution_invalid",
            ),),
        )


class PrimaryTutorProviderGateway:
    """Use exactly the configured provider and assemble control fields server-side."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: TutorJsonClient | None = None,
        max_output_tokens: int | None = None,
        timeout_seconds: float | None = None,
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

    def decide(
        self,
        *,
        run: TutorRunSnapshot,
        context: TutorContextSelection,
        thinking_sink: TutorPublicThinkingSink | None = None,
    ) -> TutorProviderResult:
        attempts: list[TutorProviderAttemptReceipt] = []
        try:
            client = (
                self._client
                if self._client is not None
                else _build_default_client(self._settings)
            )
            messages = _build_messages(run=run, context=context)
            protocol = select_llm_protocol(self._settings).value
            provider_type = self._settings.llm_provider_type
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
                        ),
                    }
                )
            try:
                thinking_mode: Literal["enabled", "disabled"] | None = (
                    "disabled"
                    if (
                        attempt_index > 1
                        and provider_type == "deepseek"
                        and self._settings.tutor_deepseek_repair_thinking_disabled
                    )
                    else None
                )
                if projector is None:
                    response = client.complete_json(
                        messages,
                        temperature=None,
                        max_tokens=self._max_output_tokens,
                        timeout_seconds=self._timeout_seconds,
                        output_schema=self._output_schema,
                        schema_name=TUTOR_PROVIDER_ITEMS_SCHEMA_NAME,
                        thinking_mode=thinking_mode,
                        capture_provider_body=True,
                    )
                else:
                    response = client.complete_json(
                        messages,
                        temperature=None,
                        max_tokens=self._max_output_tokens,
                        timeout_seconds=self._timeout_seconds,
                        output_schema=self._output_schema,
                        schema_name=TUTOR_PROVIDER_ITEMS_SCHEMA_NAME,
                        thinking_mode=thinking_mode,
                        capture_provider_body=True,
                        visible_output_observer=projector,
                    )
                _assert_raw_provider_text_safe(response.content)
                decision = parse_tutor_provider_items(response.content, run=run)
                _assert_decision_text_safe(decision)
                _assert_selected_teaching_action(context=context, decision=decision)
                _assert_teaching_focus_authority(context=context, decision=decision)
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
                repairable = True
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

    return build_tutor_provider_messages(run=run, context=context)


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
