from __future__ import annotations

import http.client
import json
import logging
import math
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Generator, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Literal, Protocol, TypeVar, cast, get_args

from app.core.config import DEEPSEEK_V4_FLASH_MODEL, Settings, get_settings
from app.agents.harness.contracts import TutorContextError, TutorExecutionProfile
from app.services.llm.completion_policy import (
    CompletionStagePolicy, estimate_completion_request_tokens, resolve_completion_stage_policy,
)
from app.services.llm.contracts import (
    LLMIncompleteReason, LLMReasoningEffort, LLMResponseDiagnostics,
    LLMResponseStatus, LLMUsage,
)
from app.services.llm.http_execution import (
    LLMHTTPExecutionError,
    current_http_execution,
)
from app.services.llm.llm_urls import deepseek_chat_completions_url, deepseek_responses_url, responses_url
from app.services.llm.provider_diagnostics import (
    ProviderBodyCapture,
    ProviderDiagnosticStore,
)


logger = logging.getLogger(__name__)

LLM_PROVIDER_RETRY_ATTEMPTS = 3
LLM_PROVIDER_RETRY_BASE_DELAY_SECONDS = 0.25
_RETRYABLE_HTTP_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_RETRYABLE_TRANSPORT_ERRORS = (
    urllib.error.URLError,
    TimeoutError,
    socket.timeout,
    ConnectionError,
    http.client.RemoteDisconnected,
)
T = TypeVar("T")


class LLMVisibleOutputObserver(Protocol):
    """Receives provider-visible output text only; never reasoning items."""

    def on_stream_start(self) -> None: ...

    def on_text_delta(self, delta: str) -> None: ...

    def on_stream_restart(self) -> None: ...

    def on_stream_complete(self) -> None: ...


class LLMConfigurationError(RuntimeError):
    pass


class LLMCallError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.diagnostic_capture: ProviderBodyCapture | None = None

    def attach_diagnostic_capture(self, capture: ProviderBodyCapture | None) -> None:
        if self.diagnostic_capture is None:
            self.diagnostic_capture = capture


class LLMInvalidResponseKind(str, Enum):
    """Bounded structural categories for a provider response rejected by the adapter."""

    UNKNOWN = "unknown"
    ENVELOPE_INVALID = "envelope_invalid"
    CONTENT_MISSING = "content_missing"
    CONTENT_NOT_JSON_OBJECT = "content_not_json_object"
    RESPONSE_INCOMPLETE = "response_incomplete"
    RESPONSE_FAILED = "response_failed"


class LLMProtocol(str, Enum):
    """One selected provider protocol per request; callers never fall through."""

    RESPONSES = "responses"
    DEEPSEEK_CHAT_COMPLETIONS = "deepseek_chat_completions"
    DEEPSEEK_RESPONSES = "deepseek_responses"


def select_llm_protocol(settings: Settings) -> LLMProtocol:
    """Select a protocol from exact provider/model configuration only.

    DeepSeek documents Responses compatibility only for the exact V4 Flash model.
    All other configured DeepSeek models retain the Chat Completions contract.
    """

    if settings.llm_provider_type != "deepseek":
        return LLMProtocol.RESPONSES
    if str(settings.llm_model or "").strip() == DEEPSEEK_V4_FLASH_MODEL:
        return LLMProtocol.DEEPSEEK_RESPONSES
    return LLMProtocol.DEEPSEEK_CHAT_COMPLETIONS


class LLMInvalidResponseError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        kind: LLMInvalidResponseKind = LLMInvalidResponseKind.UNKNOWN,
        usage: LLMUsage | None = None,
        model: str | None = None,
        response_diagnostics: LLMResponseDiagnostics | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.usage = usage
        self.model = model
        self.response_diagnostics = response_diagnostics
        self.diagnostic_capture: ProviderBodyCapture | None = None

    def attach_response_metadata(
        self, *, usage: LLMUsage | None, model: str | None,
        response_diagnostics: LLMResponseDiagnostics | None = None,
    ) -> None:
        if self.response_diagnostics is None:
            self.response_diagnostics = response_diagnostics
        if self.usage is None:
            self.usage = usage
        if self.model is None:
            self.model = model

    def attach_diagnostic_capture(self, capture: ProviderBodyCapture | None) -> None:
        if self.diagnostic_capture is None:
            self.diagnostic_capture = capture


@dataclass(frozen=True)
class LLMJsonResponse:
    content: dict[str, object]
    model: str
    usage: LLMUsage | None = None
    diagnostic_capture: ProviderBodyCapture | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    response_diagnostics: LLMResponseDiagnostics | None = None


def _require_provider_response_object(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise LLMInvalidResponseError(
            "LLM provider response must be a JSON object",
            kind=LLMInvalidResponseKind.ENVELOPE_INVALID,
        )
    return value


JsonTransport = Callable[[str, Mapping[str, str], Mapping[str, object], float], Mapping[str, object]]
TextStreamTransport = Callable[[str, Mapping[str, str], Mapping[str, object], float], Iterable[str]]


class OpenAICompatibleClient:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: JsonTransport | None = None,
        stream_transport: TextStreamTransport | None = None,
        diagnostic_store: ProviderDiagnosticStore | None = None,
        max_http_attempts: int = LLM_PROVIDER_RETRY_ATTEMPTS,
    ) -> None:
        if not 1 <= max_http_attempts <= LLM_PROVIDER_RETRY_ATTEMPTS:
            raise ValueError("max_http_attempts outside configured provider retry bound")
        self._max_http_attempts = max_http_attempts
        self._settings = settings or get_settings()
        if not self._settings.openai_compatible_configured:
            raise LLMConfigurationError("OpenAI-compatible LLM settings are incomplete")
        self._transport = transport
        self._stream_transport = stream_transport
        self._diagnostic_store = diagnostic_store

    @property
    def model(self) -> str:
        return str(self._settings.llm_model or "")

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float | None = 0.2,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
        output_schema: Mapping[str, object] | None = None,
        schema_name: str | None = None,
        thinking_mode: Literal["enabled", "disabled"] | None = None,
        reasoning_effort: Literal["low", "high", "max"] | None = None,
        capture_provider_body: bool = False,
        visible_output_observer: LLMVisibleOutputObserver | None = None,
        completion_stage: str | None = None,
    ) -> LLMJsonResponse:
        """Return one strict JSON object through the exact selected provider protocol."""

        protocol = select_llm_protocol(self._settings)
        completion_policy = None
        if completion_stage is not None:
            if not self._settings.tutor_completion_driven_enabled:
                raise ValueError("Completion-driven requests are disabled")
            completion_policy = resolve_completion_stage_policy(self._settings, completion_stage)
            if completion_policy.max_output_tokens is None:
                raise ValueError("Sidecar is not an ordinary HTTP completion stage")
            if max_tokens is not None and max_tokens != completion_policy.max_output_tokens:
                raise ValueError("max_tokens must match the completion stage output policy")
            max_tokens = completion_policy.max_output_tokens
            if timeout_seconds is not None and (not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
                raise ValueError("timeout_seconds must be finite and positive")
            timeout_seconds = min(
                completion_policy.timeout_seconds,
                timeout_seconds if timeout_seconds is not None else completion_policy.timeout_seconds,
            )
            if completion_policy.thinking_mode is not None:
                if thinking_mode not in (None, completion_policy.thinking_mode):
                    raise ValueError("thinking_mode conflicts with the completion stage policy")
                thinking_mode = completion_policy.thinking_mode
            execution = current_http_execution()
            if execution is None or execution.execution_profile is not TutorExecutionProfile.COMPLETION_DRIVEN_V1:
                raise ValueError("Completion-driven requests require their explicit HTTP execution scope")
        # DeepSeek's explicit effort applies only to enabled thinking. Preserve
        # all historical/default requests when no effort is supplied.
        if reasoning_effort is not None:
            if (type(reasoning_effort) is not str or reasoning_effort not in {"low", "high", "max"}
                    or thinking_mode != "enabled" or self._settings.llm_provider_type != "deepseek"
                    or self.model not in {DEEPSEEK_V4_FLASH_MODEL, "deepseek-v4-pro"}):
                raise ValueError("explicit DeepSeek reasoning_effort requires enabled thinking")
        max_tokens = _bounded_max_output_tokens(
            settings=self._settings,
            requested=max_tokens,
        )
        diagnostic_capture = (
            self._diagnostic_store.begin_capture()
            if capture_provider_body and self._diagnostic_store is not None
            else None
        )
        try:
            if protocol is LLMProtocol.DEEPSEEK_CHAT_COMPLETIONS:
                return self._complete_deepseek_chat_json(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout_seconds=timeout_seconds,
                    diagnostic_capture=diagnostic_capture,
                    thinking_mode=thinking_mode,
                    reasoning_effort=reasoning_effort,
                    completion_policy=completion_policy,
                )

            url = (
                deepseek_responses_url(str(self._settings.llm_base_url))
                if protocol is LLMProtocol.DEEPSEEK_RESPONSES
                else responses_url(str(self._settings.llm_base_url))
            )
            return self._complete_responses_json(
                messages,
                url=url,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_seconds=timeout_seconds,
                output_schema=output_schema,
                schema_name=schema_name,
                use_json_schema=(
                    protocol is not LLMProtocol.DEEPSEEK_RESPONSES
                    or self._settings.tutor_deepseek_responses_json_schema_enabled
                ),
                diagnostic_capture=diagnostic_capture,
                thinking_mode=thinking_mode,
                reasoning_effort=reasoning_effort,
                visible_output_observer=visible_output_observer,
                completion_policy=completion_policy,
            )
        except (LLMCallError, LLMInvalidResponseError, LLMHTTPExecutionError) as exc:
            exc.attach_diagnostic_capture(diagnostic_capture)
            raise

    def complete_text_stream(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float | None = None,
    ) -> Generator[str, None, str]:
        if self._settings.llm_provider_type == "deepseek":
            payload: dict[str, object] = {
                "model": self.model,
                "messages": _messages_to_chat_completions(messages),
                "stream": True,
            }
            if self._settings.uses_deepseek_v4_flash_responses:
                payload["max_tokens"] = self._settings.tutor_deepseek_v4_flash_max_output_tokens
            if temperature is not None:
                payload["temperature"] = temperature
            url = deepseek_chat_completions_url(str(self._settings.llm_base_url))
        else:
            instructions, input_text = _messages_to_responses_input(messages)
            payload = {
                "model": self.model,
                "input": input_text,
                "stream": True,
            }
            if instructions is not None:
                payload["instructions"] = instructions
            if temperature is not None:
                payload["temperature"] = temperature
            url = responses_url(str(self._settings.llm_base_url))
        _enforce_request_input_limit(settings=self._settings, payload=payload)
        headers = {
            "Authorization": f"Bearer {self._settings.llm_api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        timeout = float(self._settings.llm_timeout_seconds)
        try:
            chunks = (
                self._stream_transport(url, headers, payload, timeout)
                if self._stream_transport is not None
                else _post_text_stream(url, headers, payload, timeout)
            )
            full_text = ""
            for delta in chunks:
                if not delta:
                    continue
                full_text += delta
                yield delta
            if not full_text.strip():
                raise LLMInvalidResponseError("LLM provider streaming response has no content")
            return full_text
        except (LLMCallError, LLMInvalidResponseError):
            raise
        except Exception as exc:
            raise LLMCallError("LLM provider streaming transport failed") from exc

    def complete_structured_text_stream(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        output_type: type[object],
        temperature: float | None = None,
    ) -> Generator[str, None, str]:
        del output_type
        if self._settings.llm_provider_type == "deepseek":
            payload: dict[str, object] = {
                "model": self.model,
                "messages": _messages_to_chat_completions(messages, require_json_hint=True),
                "stream": True,
                "response_format": {"type": "json_object"},
            }
            if self._settings.uses_deepseek_v4_flash_responses:
                payload["max_tokens"] = self._settings.tutor_deepseek_v4_flash_max_output_tokens
            if temperature is not None:
                payload["temperature"] = temperature
            url = deepseek_chat_completions_url(str(self._settings.llm_base_url))
        else:
            instructions, input_text = _messages_to_responses_input(messages)
            payload = {
                "model": self.model,
                "input": _ensure_json_mode_hint(input_text),
                "stream": True,
                "text": {"format": {"type": "json_object"}},
            }
            if instructions is not None:
                payload["instructions"] = instructions
            if temperature is not None:
                payload["temperature"] = temperature
            url = responses_url(str(self._settings.llm_base_url))
        _enforce_request_input_limit(settings=self._settings, payload=payload)
        headers = {
            "Authorization": f"Bearer {self._settings.llm_api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        timeout = float(self._settings.llm_timeout_seconds)
        try:
            chunks = (
                self._stream_transport(url, headers, payload, timeout)
                if self._stream_transport is not None
                else _post_text_stream(url, headers, payload, timeout)
            )
            full_text = ""
            for delta in chunks:
                if not delta:
                    continue
                full_text += delta
                yield delta
            if not full_text.strip():
                raise LLMInvalidResponseError("LLM provider structured streaming response has no content")
            return full_text
        except (LLMCallError, LLMInvalidResponseError):
            raise
        except Exception as exc:
            raise LLMCallError("LLM provider structured streaming transport failed") from exc

    def _complete_responses_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        url: str,
        temperature: float | None,
        max_tokens: int | None,
        timeout_seconds: float | None,
        output_schema: Mapping[str, object] | None,
        schema_name: str | None,
        use_json_schema: bool,
        diagnostic_capture: ProviderBodyCapture | None,
        thinking_mode: Literal["enabled", "disabled"] | None,
        reasoning_effort: Literal["low", "high", "max"] | None,
        visible_output_observer: LLMVisibleOutputObserver | None,
        completion_policy: CompletionStagePolicy | None = None,
    ) -> LLMJsonResponse:
        payload = build_json_request_payload(
            self._settings, messages, temperature=temperature, max_tokens=max_tokens,
            output_schema=output_schema if use_json_schema else None, schema_name=schema_name,
            thinking_mode=thinking_mode, reasoning_effort=reasoning_effort,
        )
        _enforce_request_input_limit(settings=self._settings, payload=payload, completion_policy=completion_policy)
        headers = {
            "Authorization": f"Bearer {self._settings.llm_api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        try:
            provider_response = self._request_responses_provider(
                url=url,
                payload=payload,
                headers=headers,
                timeout_seconds=timeout_seconds,
                diagnostic_capture=diagnostic_capture,
                visible_output_observer=visible_output_observer,
            )
        except LLMInvalidResponseError as exc:
            diagnostics = exc.response_diagnostics or LLMResponseDiagnostics()
            exc.response_diagnostics = _with_request_diagnostics(diagnostics, payload)
            exc.attach_response_metadata(usage=None, model=self.model)
            raise
        except LLMHTTPExecutionError as exc:
            if exc.response_diagnostics is not None:
                exc.response_diagnostics = _with_request_diagnostics(exc.response_diagnostics, payload)
            if exc.model is None:
                exc.model = self.model
            raise
        response_diagnostics = _with_request_diagnostics(
            _extract_response_diagnostics(provider_response), payload,
        )
        usage = _extract_llm_usage(provider_response, protocol=LLMProtocol.RESPONSES)
        model = _response_model(provider_response) or self.model
        try:
            _ensure_responses_completed(provider_response)
            content = _extract_message_content(provider_response)
            parsed_content = _parse_json_object(content)
        except LLMInvalidResponseError as exc:
            exc.attach_response_metadata(
                usage=usage, model=model, response_diagnostics=response_diagnostics,
            )
            raise
        return LLMJsonResponse(
            content=parsed_content,
            model=model,
            usage=usage,
            response_diagnostics=response_diagnostics,
            diagnostic_capture=diagnostic_capture,
        )

    def _request_responses_provider(
        self,
        *,
        url: str,
        payload: Mapping[str, object],
        headers: Mapping[str, str],
        timeout_seconds: float | None = None,
        diagnostic_capture: ProviderBodyCapture | None = None,
        visible_output_observer: LLMVisibleOutputObserver | None = None,
    ) -> Mapping[str, object]:
        if (execution := current_http_execution()) is not None:
            if self._transport is not None:
                raise LLMHTTPExecutionError(
                    "custom_transport_unsupported", outcome_unknown=False,
                    physical_attempts=execution.physical_attempts,
                )
            return _post_json_stream(
                url, headers, payload,
                float(timeout_seconds if timeout_seconds is not None else self._settings.llm_timeout_seconds),
                diagnostic_capture=diagnostic_capture,
                visible_output_observer=visible_output_observer,
            )
        timeout = _resolve_timeout_seconds(self._settings.llm_timeout_seconds, timeout_seconds)
        if self._transport is not None:
            if visible_output_observer is not None:
                visible_output_observer.on_stream_start()
            try:
                response = _require_provider_response_object(
                    self._transport(url, headers, payload, timeout)
                )
            except (LLMCallError, LLMInvalidResponseError):
                raise
            except urllib.error.HTTPError as exc:
                _capture_http_error_body(exc, diagnostic_capture)
                raise LLMCallError(f"LLM provider returned HTTP {exc.code}") from exc
            except Exception as exc:
                raise LLMCallError("LLM provider transport failed") from exc
            if diagnostic_capture is not None:
                diagnostic_capture.append_mapping(response)
            if visible_output_observer is not None:
                try:
                    _ensure_responses_completed(response)
                    visible_output_observer.on_text_delta(_extract_message_content(response))
                except LLMInvalidResponseError as exc:
                    exc.attach_response_metadata(
                        usage=_extract_llm_usage(response, protocol=LLMProtocol.RESPONSES),
                        model=_response_model(response) or self.model,
                        response_diagnostics=_extract_response_diagnostics(response),
                    )
                    raise
                visible_output_observer.on_stream_complete()
            return response
        return _post_json_stream(
            url,
            headers,
            payload,
            timeout,
            diagnostic_capture=diagnostic_capture,
            visible_output_observer=visible_output_observer,
            max_attempts=self._max_http_attempts,
        )

    def _complete_deepseek_chat_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float | None,
        max_tokens: int | None,
        timeout_seconds: float | None,
        diagnostic_capture: ProviderBodyCapture | None,
        thinking_mode: Literal["enabled", "disabled"] | None,
        reasoning_effort: Literal["low", "high", "max"] | None,
        completion_policy: CompletionStagePolicy | None = None,
    ) -> LLMJsonResponse:
        payload = build_json_request_payload(
            self._settings, messages, temperature=temperature, max_tokens=max_tokens,
            thinking_mode=thinking_mode, reasoning_effort=reasoning_effort,
        )
        _enforce_request_input_limit(settings=self._settings, payload=payload, completion_policy=completion_policy)
        headers = {
            "Authorization": f"Bearer {self._settings.llm_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        url = deepseek_chat_completions_url(str(self._settings.llm_base_url))
        execution = current_http_execution()
        timeout = (
            float(timeout_seconds if timeout_seconds is not None else self._settings.llm_timeout_seconds)
            if execution is not None
            else _resolve_timeout_seconds(self._settings.llm_timeout_seconds, timeout_seconds)
        )
        if execution is not None and self._transport is not None:
            raise LLMHTTPExecutionError(
                "custom_transport_unsupported", outcome_unknown=False,
                physical_attempts=execution.physical_attempts,
            )
        if self._transport is not None:
            try:
                provider_response = _require_provider_response_object(
                    self._transport(url, headers, payload, timeout)
                )
                if diagnostic_capture is not None:
                    diagnostic_capture.append_mapping(provider_response)
            except (LLMCallError, LLMInvalidResponseError):
                raise
            except urllib.error.HTTPError as exc:
                _capture_http_error_body(exc, diagnostic_capture)
                raise LLMCallError(f"LLM provider returned HTTP {exc.code}") from exc
            except Exception as exc:
                raise LLMCallError("LLM provider transport failed") from exc
        else:
            provider_response = _post_json(
                url,
                headers,
                payload,
                timeout,
                diagnostic_capture=diagnostic_capture,
                max_attempts=self._max_http_attempts,
            )
        usage = _extract_llm_usage(provider_response, protocol=LLMProtocol.DEEPSEEK_CHAT_COMPLETIONS)
        model = _response_model(provider_response) or self.model
        # Even syntactically valid JSON is not a completed answer if the provider
        # exhausted its shared thinking/final-output budget or filtered it.
        choices = provider_response.get("choices")
        first = choices[0] if isinstance(choices, list) and choices else None
        finish = first.get("finish_reason") if isinstance(first, Mapping) else None
        if isinstance(finish, str) and finish in {"length", "content_filter"}:
            diagnostics = LLMResponseDiagnostics(
                response_status="incomplete",
                incomplete_reason="max_output_tokens" if finish == "length" else "content_filter",
                requested_max_output_tokens=max_tokens,
                requested_reasoning_effort=reasoning_effort,
            )
            raise LLMInvalidResponseError("DeepSeek response is incomplete",
                kind=LLMInvalidResponseKind.RESPONSE_INCOMPLETE, usage=usage, model=model,
                response_diagnostics=diagnostics)
        try:
            content = _extract_message_content(provider_response)
            parsed_content = _parse_json_object(content)
        except LLMInvalidResponseError as exc:
            exc.attach_response_metadata(usage=usage, model=model)
            raise
        return LLMJsonResponse(
            content=parsed_content,
            model=model,
            usage=usage,
            diagnostic_capture=diagnostic_capture,
        )


def _post_json_stream(
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, object],
    timeout: float,
    *,
    diagnostic_capture: ProviderBodyCapture | None = None,
    visible_output_observer: LLMVisibleOutputObserver | None = None,
    max_attempts: int = LLM_PROVIDER_RETRY_ATTEMPTS,
) -> Mapping[str, object]:
    if (execution := current_http_execution()) is not None:
        def started(restart: bool) -> None:
            if visible_output_observer is not None:
                if restart:
                    visible_output_observer.on_stream_restart()
                visible_output_observer.on_stream_start()

        def consume(lines: Iterable[bytes]) -> Mapping[str, object]:
            try:
                return _parse_responses_stream(
                    lines, diagnostic_capture=diagnostic_capture,
                    visible_output_observer=visible_output_observer,
                )
            except LLMInvalidResponseError as exc:
                if (exc.response_diagnostics is not None
                        and exc.response_diagnostics.response_status == "missing_terminal"):
                    error = LLMHTTPExecutionError(
                        "transport_unknown", outcome_unknown=True,
                        physical_attempts=execution.physical_attempts,
                    )
                    error.usage, error.model = exc.usage, exc.model
                    error.response_diagnostics = exc.response_diagnostics
                    raise error from exc
                raise

        parsed = execution.post(
            url, headers, payload, timeout, consume, on_start=started,
            capture=diagnostic_capture,
        )
        if visible_output_observer is not None:
            visible_output_observer.on_stream_complete()
        return parsed
    request_count = 0

    def request_once() -> Mapping[str, object]:
        nonlocal request_count
        request_count += 1
        if visible_output_observer is not None:
            if request_count > 1:
                visible_output_observer.on_stream_restart()
            visible_output_observer.on_stream_start()
        request = _provider_request(url, headers, payload)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            parsed = _parse_responses_stream(
                response,
                diagnostic_capture=diagnostic_capture,
                visible_output_observer=visible_output_observer,
            )
        if visible_output_observer is not None:
            visible_output_observer.on_stream_complete()
        return parsed

    return _request_with_retries(
        "JSON stream",
        request_once,
        diagnostic_capture=diagnostic_capture,
        max_attempts=max_attempts,
    )


def _post_json(
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, object],
    timeout: float,
    *,
    diagnostic_capture: ProviderBodyCapture | None = None,
    max_attempts: int = LLM_PROVIDER_RETRY_ATTEMPTS,
) -> Mapping[str, object]:
    if (execution := current_http_execution()) is not None:
        def consume(lines: Iterable[bytes]) -> Mapping[str, object]:
            raw_body = b"".join(lines)
            if diagnostic_capture is not None:
                diagnostic_capture.append(raw_body)
            try:
                parsed = json.loads(raw_body)
            except (ValueError, UnicodeDecodeError) as exc:
                raise LLMInvalidResponseError(
                    "LLM provider returned invalid JSON",
                    kind=LLMInvalidResponseKind.ENVELOPE_INVALID,
                ) from exc
            return _require_provider_response_object(parsed)

        return execution.post(
            url, headers, payload, timeout, consume, capture=diagnostic_capture,
        )
    def request_once() -> str:
        request = _provider_request(url, headers, payload)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_body = response.read()
            if diagnostic_capture is not None:
                diagnostic_capture.append(raw_body)
            body = raw_body.decode("utf-8", "replace").strip()

        return body

    body = _request_with_retries(
        "JSON",
        request_once,
        diagnostic_capture=diagnostic_capture,
        max_attempts=max_attempts,
    )

    if not body:
        raise LLMInvalidResponseError(
            "LLM provider returned an empty response",
            kind=LLMInvalidResponseKind.ENVELOPE_INVALID,
        )
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise LLMInvalidResponseError(
            "LLM provider returned invalid JSON",
            kind=LLMInvalidResponseKind.ENVELOPE_INVALID,
        ) from exc
    return _require_provider_response_object(parsed)


def _safe_transport_error(exc: BaseException) -> str:
    """Return a log-safe transport category without preserving provider detail."""

    if isinstance(exc, urllib.error.URLError):
        return "URLError"
    return type(exc).__name__


def _resolve_timeout_seconds(configured_timeout: float, timeout_seconds: float | None) -> float:
    if timeout_seconds is None:
        return float(configured_timeout)
    return max(float(configured_timeout), float(timeout_seconds))


def _bounded_max_output_tokens(
    *,
    settings: Settings,
    requested: int | None,
) -> int | None:
    """Apply the exact model hard cap without widening smaller caller budgets."""

    if not settings.uses_deepseek_v4_flash_responses:
        return requested
    maximum = settings.tutor_deepseek_v4_flash_max_output_tokens
    if requested is None:
        return maximum
    if requested <= 0:
        raise ValueError("max_tokens must be positive")
    if requested > maximum:
        raise ValueError("max_tokens exceeds the configured DeepSeek Flash maximum")
    return requested


def _enforce_request_input_limit(
    *,
    settings: Settings,
    payload: Mapping[str, object],
    completion_policy: CompletionStagePolicy | None = None,
) -> None:
    """Reject oversized exact-model input before any provider transport."""

    if completion_policy is not None:
        capability = completion_policy.context_capability
        if capability is None:
            raise ValueError("Completion stage has no ordinary HTTP context capability")
        if estimate_completion_request_tokens(payload, capability=capability) > capability.input_hard_limit:
            raise TutorContextError("TUTOR_CONTEXT_REQUEST_OVERFLOW")
        return
    if not settings.uses_deepseek_v4_flash_responses:
        return
    input_payload = {
        key: payload[key]
        for key in ("instructions", "input", "messages", "text", "response_format")
        if key in payload
    }
    encoded = json.dumps(
        input_payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    estimated_tokens = max(1, (len(encoded) + 3) // 4)
    if estimated_tokens > settings.tutor_deepseek_v4_flash_input_limit_tokens:
        raise ValueError("LLM request input exceeds the configured DeepSeek Flash maximum")


def build_json_request_payload(
    settings: Settings, messages: Sequence[Mapping[str, str]], *,
    temperature: float | None = None, max_tokens: int | None = None,
    output_schema: Mapping[str, object] | None = None, schema_name: str | None = None,
    thinking_mode: Literal["enabled", "disabled"] | None = None,
    reasoning_effort: Literal["low", "high", "max"] | None = None,
) -> dict[str, object]:
    """Pure request representation shared by planning and the final transport.

    Includes JSON hints, role conversion, schemas and all protocol wrappers.
    Callers must still apply the stage/legacy policy and final input guard.
    """
    protocol = select_llm_protocol(settings)
    if protocol is LLMProtocol.DEEPSEEK_CHAT_COMPLETIONS:
        payload: dict[str, object] = {
            "model": str(settings.llm_model or ""),
            "messages": _messages_to_chat_completions(messages, require_json_hint=True),
            "response_format": {"type": "json_object"},
        }
        if thinking_mode is not None:
            payload["thinking"] = {"type": thinking_mode}
        if reasoning_effort is not None:
            payload["reasoning_effort"] = reasoning_effort
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
    else:
        instructions, input_text = _messages_to_responses_input(messages)
        text_format: dict[str, object] = {"type": "json_object"}
        if output_schema is not None and (
            protocol is not LLMProtocol.DEEPSEEK_RESPONSES
            or settings.tutor_deepseek_responses_json_schema_enabled
        ):
            text_format = {
                "type": "json_schema", "name": schema_name or "structured_output",
                "schema": dict(output_schema), "strict": True,
            }
        payload = {
            "model": str(settings.llm_model or ""),
            "input": _ensure_json_mode_hint(input_text), "stream": True,
            "text": {"format": text_format},
        }
        if instructions is not None:
            payload["instructions"] = instructions
        if thinking_mode is not None and settings.llm_provider_type == "deepseek":
            payload["reasoning"] = {"effort": "none" if thinking_mode == "disabled" else (reasoning_effort or "high")}
        if max_tokens is not None:
            payload["max_output_tokens"] = max_tokens
    if temperature is not None:
        payload["temperature"] = temperature
    return payload


def _post_text_stream(
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, object],
    timeout: float,
) -> Generator[str, None, None]:
    for attempt in range(1, LLM_PROVIDER_RETRY_ATTEMPTS + 1):
        yielded_any = False
        try:
            request = _provider_request(url, headers, payload)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                for delta in _iter_response_text_deltas(response):
                    yielded_any = True
                    yield delta
            return
        except urllib.error.HTTPError as exc:
            if yielded_any or not _should_retry_http_error(exc) or attempt >= LLM_PROVIDER_RETRY_ATTEMPTS:
                raise LLMCallError(f"LLM provider returned HTTP {exc.code}") from exc
            _log_retry("text stream", attempt, f"HTTP {exc.code}")
        except _RETRYABLE_TRANSPORT_ERRORS as exc:
            if yielded_any or attempt >= LLM_PROVIDER_RETRY_ATTEMPTS:
                logger.warning("LLM provider text stream request failed: %s", _safe_transport_error(exc))
                raise LLMCallError("LLM provider request failed") from exc
            _log_retry("text stream", attempt, _safe_transport_error(exc))
        _sleep_before_retry(attempt)


def _provider_request(
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, object],
) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=dict(headers),
        method="POST",
    )


def _request_with_retries(
    operation_name: str,
    request_once: Callable[[], T],
    *,
    diagnostic_capture: ProviderBodyCapture | None = None,
    max_attempts: int = LLM_PROVIDER_RETRY_ATTEMPTS,
) -> T:
    if not 1 <= max_attempts <= LLM_PROVIDER_RETRY_ATTEMPTS:
        raise ValueError("max_attempts outside provider retry bound")
    for attempt in range(1, max_attempts + 1):
        try:
            return request_once()
        except urllib.error.HTTPError as exc:
            _capture_http_error_body(exc, diagnostic_capture)
            if not _should_retry_http_error(exc) or attempt >= max_attempts:
                raise LLMCallError(f"LLM provider returned HTTP {exc.code}") from exc
            _log_retry(operation_name, attempt, f"HTTP {exc.code}")
        except _RETRYABLE_TRANSPORT_ERRORS as exc:
            if attempt >= max_attempts:
                logger.warning("LLM provider %s request failed: %s", operation_name, _safe_transport_error(exc))
                raise LLMCallError("LLM provider request failed") from exc
            _log_retry(operation_name, attempt, _safe_transport_error(exc))
        _sleep_before_retry(attempt)
    raise LLMCallError("LLM provider retry attempts exhausted")


def _capture_http_error_body(
    exc: urllib.error.HTTPError,
    capture: ProviderBodyCapture | None,
) -> None:
    if capture is None or capture.remaining_capacity <= 0:
        return
    try:
        body = exc.read(capture.remaining_capacity + 1)
    except Exception:
        return
    if isinstance(body, bytes):
        capture.append(body)


def _should_retry_http_error(exc: urllib.error.HTTPError) -> bool:
    return int(exc.code) in _RETRYABLE_HTTP_STATUS_CODES


def _log_retry(operation_name: str, attempt: int, reason: str) -> None:
    logger.warning(
        "LLM provider %s request failed; retrying (%s/%s): %s",
        operation_name,
        attempt,
        LLM_PROVIDER_RETRY_ATTEMPTS,
        reason,
    )


def _sleep_before_retry(attempt: int) -> None:
    time.sleep(LLM_PROVIDER_RETRY_BASE_DELAY_SECONDS * attempt)


def _iter_response_text_deltas(response: Iterable[bytes]) -> Generator[str, None, None]:
    pending_data: list[str] = []
    yielded_delta = False

    def flush_frame() -> list[str]:
        nonlocal pending_data, yielded_delta
        if not pending_data:
            return []

        payload_text = "\n".join(pending_data).strip()
        pending_data = []
        if not payload_text or payload_text == "[DONE]":
            return []

        try:
            parsed = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            raise LLMInvalidResponseError(
                "LLM provider stream returned invalid JSON",
                kind=LLMInvalidResponseKind.ENVELOPE_INVALID,
            ) from exc
        _require_provider_response_object(parsed)

        event_type = str(parsed.get("type", ""))
        if event_type == "response.output_text.delta":
            delta = parsed.get("delta")
            if isinstance(delta, str) and delta:
                yielded_delta = True
                return [delta]
        if event_type == "response.output_text.done" and not yielded_delta:
            text = parsed.get("text")
            if isinstance(text, str) and text:
                yielded_delta = True
                return [text]
        if event_type == "response.completed" and not yielded_delta:
            maybe_response = parsed.get("response")
            if isinstance(maybe_response, Mapping):
                text = _extract_message_content(maybe_response)
                yielded_delta = True
                return [text]

        choices = parsed.get("choices")
        if isinstance(choices, Sequence) and not isinstance(choices, (str, bytes)):
            deltas: list[str] = []
            for choice in choices:
                if not isinstance(choice, Mapping):
                    continue
                delta = choice.get("delta")
                if isinstance(delta, Mapping) and isinstance(delta.get("content"), str):
                    content_delta = str(delta["content"])
                    if content_delta:
                        deltas.append(content_delta)
                elif isinstance(choice.get("text"), str) and choice["text"]:
                    deltas.append(str(choice["text"]))
            if deltas:
                yielded_delta = True
                return deltas
        return []

    for raw_line in response:
        line = raw_line.decode("utf-8", "replace").rstrip("\r\n")
        if not line:
            for delta in flush_frame():
                yield delta
            continue
        if line.startswith("event: "):
            continue
        if line.startswith("data: "):
            pending_data.append(line[len("data: ") :])
            continue

    for delta in flush_frame():
        yield delta


def _parse_responses_stream(
    response: Iterable[bytes],
    *,
    diagnostic_capture: ProviderBodyCapture | None = None,
    visible_output_observer: LLMVisibleOutputObserver | None = None,
) -> Mapping[str, object]:
    latest_response: dict[str, object] | None = None
    latest_text: str | None = None
    observed_response: Mapping[str, object] = {}
    pending_data: list[str] = []

    def flush_frame() -> None:
        nonlocal latest_response, latest_text, pending_data, observed_response
        if not pending_data:
            return

        payload_text = "\n".join(pending_data).strip()
        pending_data = []
        if not payload_text or payload_text == "[DONE]":
            return

        try:
            parsed = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            raise LLMInvalidResponseError(
                "LLM provider stream returned invalid JSON",
                kind=LLMInvalidResponseKind.ENVELOPE_INVALID,
            ) from exc
        _require_provider_response_object(parsed)

        event_type = str(parsed.get("type", ""))
        maybe_response = parsed.get("response")
        if isinstance(maybe_response, Mapping):
            observed_response = maybe_response
        if isinstance(maybe_response, Mapping) and event_type == "response.completed":
            latest_response = dict(maybe_response)
            latest_response.setdefault("status", "completed")

        if event_type == "response.output_text.delta":
            delta = parsed.get("delta")
            if isinstance(delta, str):
                latest_text = (latest_text or "") + delta
                if visible_output_observer is not None and delta:
                    visible_output_observer.on_text_delta(delta)
        elif event_type == "response.output_text.done":
            text = parsed.get("text")
            if isinstance(text, str) and text.strip():
                latest_text = text.strip()
        elif event_type == "response.incomplete":
            response_metadata = maybe_response if isinstance(maybe_response, Mapping) else {}
            raise LLMInvalidResponseError(
                "LLM provider response was incomplete",
                kind=LLMInvalidResponseKind.RESPONSE_INCOMPLETE,
                usage=_extract_llm_usage(response_metadata, protocol=LLMProtocol.RESPONSES),
                model=_response_model(response_metadata) or None,
                response_diagnostics=_extract_response_diagnostics(
                    response_metadata, status_override=event_type.removeprefix("response."),
                    visible_text=latest_text,
                ),
            )
        elif event_type == "response.failed":
            response_metadata = maybe_response if isinstance(maybe_response, Mapping) else {}
            raise LLMInvalidResponseError(
                "LLM provider response failed",
                kind=LLMInvalidResponseKind.RESPONSE_FAILED,
                usage=_extract_llm_usage(response_metadata, protocol=LLMProtocol.RESPONSES),
                model=_response_model(response_metadata) or None,
                response_diagnostics=_extract_response_diagnostics(
                    response_metadata, status_override=event_type.removeprefix("response."),
                    visible_text=latest_text,
                ),
            )

    try:
        for raw_line in response:
            if diagnostic_capture is not None:
                diagnostic_capture.append(raw_line)
            line = raw_line.decode("utf-8", "replace").rstrip("\r\n")
            if not line:
                flush_frame()
                continue
            if line.startswith("event: "):
                continue
            if line.startswith("data: "):
                pending_data.append(line[len("data: ") :])
                continue

        flush_frame()
    except LLMHTTPExecutionError as exc:
        exc.usage = _extract_llm_usage(observed_response, protocol=LLMProtocol.RESPONSES)
        exc.model = _response_model(observed_response) or None
        exc.response_diagnostics = _extract_response_diagnostics(
            observed_response, status_override="missing_terminal", visible_text=latest_text,
        )
        raise
    except LLMInvalidResponseError as exc:
        exc.attach_response_metadata(
            usage=_extract_llm_usage(observed_response, protocol=LLMProtocol.RESPONSES),
            model=_response_model(observed_response) or None,
            response_diagnostics=_extract_response_diagnostics(
                observed_response, status_override="missing_terminal", visible_text=latest_text,
            ),
        )
        raise
    if latest_response is None:
        raise LLMInvalidResponseError(
            "LLM provider stream ended without a terminal response",
            kind=LLMInvalidResponseKind.ENVELOPE_INVALID,
            usage=_extract_llm_usage(observed_response, protocol=LLMProtocol.RESPONSES),
            model=_response_model(observed_response) or None,
            response_diagnostics=_extract_response_diagnostics(
                observed_response, status_override="missing_terminal", visible_text=latest_text,
            ),
        )
    if latest_text is not None and not _has_message_content(latest_response):
        latest_response = dict(latest_response)
        latest_response["output"] = [
            {
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": latest_text.strip(),
                    }
                ],
            }
        ]
    return latest_response


def _extract_response_diagnostics(
    provider_response: Mapping[str, object], *, status_override: str | None = None,
    visible_text: str | None = None,
) -> LLMResponseDiagnostics:
    response = _normalize_response_payload(provider_response)
    status = status_override or response.get("status")
    if status is None and provider_response.get("type") == "response.completed":
        status = "completed"
    safe_status = status if isinstance(status, str) and status in get_args(LLMResponseStatus) else "unknown"
    details = response.get("incomplete_details")
    reason = details.get("reason") if isinstance(details, Mapping) else None
    safe_reason = (
        reason if isinstance(reason, str) and reason in get_args(LLMIncompleteReason)
        else "unknown" if reason is not None else None
    )
    visible_chars = 0
    output = response.get("output")
    if isinstance(output, Sequence) and not isinstance(output, (str, bytes)):
        for item in output:
            if not isinstance(item, Mapping) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, Sequence) or isinstance(content, (str, bytes)):
                continue
            for part in content:
                if isinstance(part, Mapping) and part.get("type") == "output_text":
                    text = part.get("text")
                    if isinstance(text, str):
                        visible_chars += len(text)
    if visible_text is not None:
        visible_chars = max(visible_chars, len(visible_text))
    return LLMResponseDiagnostics(
        response_status=cast(LLMResponseStatus, safe_status),
        incomplete_reason=cast(LLMIncompleteReason | None, safe_reason),
        visible_output_chars=visible_chars,
    )


def _with_request_diagnostics(
    diagnostics: LLMResponseDiagnostics, payload: Mapping[str, object],
) -> LLMResponseDiagnostics:
    _, budget = _optional_usage_int(payload, ("max_output_tokens",))
    reasoning = payload.get("reasoning")
    effort = reasoning.get("effort") if isinstance(reasoning, Mapping) else None
    safe_effort = effort if isinstance(effort, str) and effort in get_args(LLMReasoningEffort) else None
    return replace(
        diagnostics, requested_max_output_tokens=budget,
        requested_reasoning_effort=cast(LLMReasoningEffort | None, safe_effort),
    )


def _ensure_responses_completed(provider_response: Mapping[str, object]) -> None:
    """Reject nonterminal/failed Responses envelopes before reading visible output."""

    response = _normalize_response_payload(provider_response)
    response_type = str(provider_response.get("type", ""))
    status = str(response.get("status", "")).strip().lower()
    if response_type == "response.incomplete" or status == "incomplete":
        raise LLMInvalidResponseError(
            "LLM provider response was incomplete",
            kind=LLMInvalidResponseKind.RESPONSE_INCOMPLETE,
        )
    if response_type == "response.failed" or status == "failed":
        raise LLMInvalidResponseError(
            "LLM provider response failed",
            kind=LLMInvalidResponseKind.RESPONSE_FAILED,
        )
    if (response_type and response_type != "response.completed") or (status and status != "completed"):
        raise LLMInvalidResponseError(
            "LLM provider response did not complete",
            kind=LLMInvalidResponseKind.ENVELOPE_INVALID,
        )


def _has_message_content(provider_response: Mapping[str, object]) -> bool:
    try:
        _extract_message_content(provider_response)
    except LLMInvalidResponseError:
        return False
    return True


def _response_from_text(text: str, *, model: str) -> dict[str, object]:
    stripped = text.strip()
    if not stripped:
        raise LLMInvalidResponseError(
            "LLM provider response has no message content",
            kind=LLMInvalidResponseKind.CONTENT_MISSING,
        )
    return {
        "model": model,
        "output": [
            {
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": stripped,
                    }
                ],
            }
        ],
    }


def _messages_to_responses_input(messages: Sequence[Mapping[str, str]]) -> tuple[str | None, str]:
    instructions: list[str] = []
    prompt_parts: list[str] = []
    for message in messages:
        role = str(message.get("role", "")).strip().lower()
        content = str(message.get("content", "")).strip()
        if not content:
            continue
        if role == "system":
            instructions.append(content)
        else:
            prompt_parts.append(content)

    input_text = "\n\n".join(prompt_parts).strip()
    if not input_text:
        raise LLMInvalidResponseError("LLM request has no user content")
    combined_instructions = "\n\n".join(instructions).strip() or None
    return combined_instructions, input_text


def _messages_to_chat_completions(
    messages: Sequence[Mapping[str, str]],
    *,
    require_json_hint: bool = False,
) -> list[dict[str, str]]:
    chat_messages: list[dict[str, str]] = []
    last_user_index: int | None = None
    has_json_hint = False
    for message in messages:
        role = str(message.get("role", "")).strip().lower()
        content = str(message.get("content", "")).strip()
        if not content:
            continue
        if role not in {"system", "user", "assistant", "tool"}:
            role = "user"
        if "json" in content.lower():
            has_json_hint = True
        if role == "user":
            last_user_index = len(chat_messages)
        chat_messages.append({"role": role, "content": content})

    if last_user_index is None:
        raise LLMInvalidResponseError("LLM request has no user content")

    if require_json_hint and not has_json_hint:
        chat_messages[last_user_index]["content"] = (
            f"{chat_messages[last_user_index]['content']}\n\nReturn the final answer as a JSON object."
        )
    return chat_messages


def _ensure_json_mode_hint(input_text: str) -> str:
    if "json" in input_text.lower():
        return input_text
    return f"{input_text}\n\nReturn the final answer as a JSON object."


def _extract_message_content(provider_response: Mapping[str, object]) -> str:
    response = _normalize_response_payload(provider_response)
    has_output = "output" in response
    has_choices = "choices" in response
    invalid_envelope = False

    if has_output:
        output = response.get("output")
        if not isinstance(output, Sequence) or isinstance(output, (str, bytes)):
            invalid_envelope = True
        else:
            for item in output:
                if not isinstance(item, Mapping):
                    continue
                content = item.get("content")
                if not isinstance(content, Sequence) or isinstance(content, (str, bytes)):
                    continue
                for part in content:
                    if not isinstance(part, Mapping):
                        continue
                    if str(part.get("type", "")) != "output_text":
                        continue
                    text = part.get("text")
                    if isinstance(text, str) and text.strip():
                        return text.strip()

    if has_choices:
        choices = response.get("choices")
        if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)):
            invalid_envelope = True
        else:
            for choice in choices:
                if not isinstance(choice, Mapping):
                    continue
                message = choice.get("message")
                if isinstance(message, Mapping):
                    choice_content: object = message.get("content")
                else:
                    choice_content = choice.get("text")
                if isinstance(choice_content, str) and choice_content.strip():
                    return choice_content.strip()
                if isinstance(choice_content, Sequence) and not isinstance(choice_content, (str, bytes)):
                    text_parts = [
                        str(part.get("text", "")).strip()
                        for part in choice_content
                        if isinstance(part, Mapping) and str(part.get("type", "")) == "text"
                    ]
                    combined = "\n".join(part for part in text_parts if part)
                    if combined:
                        return combined

    if invalid_envelope or (not has_output and not has_choices):
        raise LLMInvalidResponseError(
            "LLM provider response does not use a supported output envelope",
            kind=LLMInvalidResponseKind.ENVELOPE_INVALID,
        )
    raise LLMInvalidResponseError(
        "LLM provider response has no message content",
        kind=LLMInvalidResponseKind.CONTENT_MISSING,
    )


def _extract_llm_usage(
    provider_response: Mapping[str, object],
    *,
    protocol: LLMProtocol,
) -> LLMUsage | None:
    response = _normalize_response_payload(provider_response)
    raw_usage = response.get("usage")
    if not isinstance(raw_usage, Mapping):
        return None

    if protocol is LLMProtocol.DEEPSEEK_CHAT_COMPLETIONS:
        paths = {
            "input_tokens": ("prompt_tokens",),
            "cached_input_tokens": ("prompt_tokens_details", "cached_tokens"),
            "output_tokens": ("completion_tokens",),
            "total_tokens": ("total_tokens",),
        }
        reasoning_paths = (
            ("completion_tokens_details", "reasoning_tokens"),
            ("output_tokens_details", "reasoning_tokens"),
        )
    else:
        paths = {
            "input_tokens": ("input_tokens",),
            "cached_input_tokens": ("input_tokens_details", "cached_tokens"),
            "output_tokens": ("output_tokens",),
            "total_tokens": ("total_tokens",),
        }
        reasoning_paths = (
            ("output_tokens_details", "reasoning_tokens"),
            ("completion_tokens_details", "reasoning_tokens"),
        )

    values: dict[str, int | None] = {}
    for field_name, field_path in paths.items():
        valid, value = _optional_usage_int(raw_usage, field_path)
        if not valid:
            return None
        values[field_name] = value

    reasoning_tokens: int | None = None
    for field_path in reasoning_paths:
        valid, value = _optional_usage_int(raw_usage, field_path)
        if not valid:
            return None
        if value is not None:
            reasoning_tokens = value
            break
    values["reasoning_tokens"] = reasoning_tokens

    try:
        usage = LLMUsage(**values)
    except ValueError:
        return None
    return usage if usage.usage_available else None


def _optional_usage_int(
    value: Mapping[str, object],
    path: tuple[str, ...],
) -> tuple[bool, int | None]:
    current: object = value
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return True, None
        current = current[key]
    if current is None:
        return True, None
    if isinstance(current, bool) or not isinstance(current, int) or current < 0:
        return False, None
    return True, current


def _response_model(provider_response: Mapping[str, object]) -> str:
    response = _normalize_response_payload(provider_response)
    model = response.get("model")
    if isinstance(model, str):
        stripped = model.strip()
        if stripped:
            return stripped
    return ""


def _normalize_response_payload(provider_response: Mapping[str, object]) -> Mapping[str, object]:
    if provider_response.get("type") == "response.completed":
        nested = provider_response.get("response")
        if isinstance(nested, Mapping):
            return nested
    nested_response = provider_response.get("response")
    if isinstance(nested_response, Mapping) and provider_response.get("object") != "response":
        return nested_response
    return provider_response


def _parse_json_object(content: str) -> dict[str, object]:
    try:
        parsed = json.loads(_strip_json_fence(content))
    except json.JSONDecodeError as exc:
        raise LLMInvalidResponseError(
            "LLM message content is not valid JSON",
            kind=LLMInvalidResponseKind.CONTENT_NOT_JSON_OBJECT,
        ) from exc
    if not isinstance(parsed, dict):
        raise LLMInvalidResponseError(
            "LLM message content must be a JSON object",
            kind=LLMInvalidResponseKind.CONTENT_NOT_JSON_OBJECT,
        )
    return parsed


def _strip_json_fence(content: str) -> str:
    stripped = content.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()
