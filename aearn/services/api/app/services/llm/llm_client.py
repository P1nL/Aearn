from __future__ import annotations

import http.client
import json
import logging
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Generator, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TypeVar

from app.core.config import Settings, get_settings
from app.services.llm.llm_urls import deepseek_chat_completions_url, responses_url


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


class LLMConfigurationError(RuntimeError):
    pass


class LLMCallError(RuntimeError):
    pass


class LLMInvalidResponseError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMJsonResponse:
    content: dict[str, object]
    model: str


JsonTransport = Callable[[str, Mapping[str, str], Mapping[str, object], float], Mapping[str, object]]
TextStreamTransport = Callable[[str, Mapping[str, str], Mapping[str, object], float], Iterable[str]]


class OpenAICompatibleClient:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: JsonTransport | None = None,
        stream_transport: TextStreamTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        if not self._settings.openai_compatible_configured:
            raise LLMConfigurationError("OpenAI-compatible LLM settings are incomplete")
        self._transport = transport
        self._stream_transport = stream_transport

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
    ) -> LLMJsonResponse:
        if self._settings.llm_provider_type == "deepseek":
            return self._complete_deepseek_json(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_seconds=timeout_seconds,
            )

        instructions, input_text = _messages_to_responses_input(messages)
        input_text = _ensure_json_mode_hint(input_text)
        payload: dict[str, object] = {
            "model": self.model,
            "input": input_text,
            "stream": True,
            "text": {"format": {"type": "json_object"}},
        }
        if instructions is not None:
            payload["instructions"] = instructions
        if max_tokens is not None:
            payload["max_output_tokens"] = max_tokens
        headers = {
            "Authorization": f"Bearer {self._settings.llm_api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        provider_response = self._request_provider(payload, headers, timeout_seconds=timeout_seconds)
        content = _extract_message_content(provider_response)
        model = _response_model(provider_response) or self.model
        return LLMJsonResponse(content=_parse_json_object(content), model=model)

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

    def _request_provider(
        self,
        payload: Mapping[str, object],
        headers: Mapping[str, str],
        *,
        timeout_seconds: float | None = None,
    ) -> Mapping[str, object]:
        url = responses_url(str(self._settings.llm_base_url))
        timeout = _resolve_timeout_seconds(self._settings.llm_timeout_seconds, timeout_seconds)
        if self._transport is not None:
            try:
                return self._transport(url, headers, payload, timeout)
            except (LLMCallError, LLMInvalidResponseError):
                raise
            except Exception as exc:
                raise LLMCallError("LLM provider transport failed") from exc
        return _post_json_stream(url, headers, payload, timeout)

    def _complete_deepseek_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float | None,
        max_tokens: int | None,
        timeout_seconds: float | None,
    ) -> LLMJsonResponse:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": _messages_to_chat_completions(messages, require_json_hint=True),
            "response_format": {"type": "json_object"},
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        headers = {
            "Authorization": f"Bearer {self._settings.llm_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        url = deepseek_chat_completions_url(str(self._settings.llm_base_url))
        timeout = _resolve_timeout_seconds(self._settings.llm_timeout_seconds, timeout_seconds)
        if self._transport is not None:
            try:
                provider_response = self._transport(url, headers, payload, timeout)
            except (LLMCallError, LLMInvalidResponseError):
                raise
            except Exception as exc:
                raise LLMCallError("LLM provider transport failed") from exc
        else:
            provider_response = _post_json(url, headers, payload, timeout)
        content = _extract_message_content(provider_response)
        model = _response_model(provider_response) or self.model
        return LLMJsonResponse(content=_parse_json_object(content), model=model)


def _post_json_stream(
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, object],
    timeout: float,
) -> Mapping[str, object]:
    def request_once() -> Mapping[str, object]:
        request = _provider_request(url, headers, payload)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _parse_responses_stream(response)

    return _request_with_retries("JSON stream", request_once)


def _post_json(
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, object],
    timeout: float,
) -> Mapping[str, object]:
    def request_once() -> str:
        request = _provider_request(url, headers, payload)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace").strip()

        return body

    body = _request_with_retries("JSON", request_once)

    if not body:
        raise LLMInvalidResponseError("LLM provider returned an empty response")
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise LLMInvalidResponseError("LLM provider returned invalid JSON") from exc
    if not isinstance(parsed, Mapping):
        raise LLMInvalidResponseError("LLM provider response must be a JSON object")
    return parsed


def _safe_transport_error(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        return f"{type(reason).__name__}: {reason}"
    return f"{type(exc).__name__}: {exc}"


def _resolve_timeout_seconds(configured_timeout: float, timeout_seconds: float | None) -> float:
    if timeout_seconds is None:
        return float(configured_timeout)
    return max(float(configured_timeout), float(timeout_seconds))


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


def _request_with_retries(operation_name: str, request_once: Callable[[], T]) -> T:
    for attempt in range(1, LLM_PROVIDER_RETRY_ATTEMPTS + 1):
        try:
            return request_once()
        except urllib.error.HTTPError as exc:
            if not _should_retry_http_error(exc) or attempt >= LLM_PROVIDER_RETRY_ATTEMPTS:
                raise LLMCallError(f"LLM provider returned HTTP {exc.code}") from exc
            _log_retry(operation_name, attempt, f"HTTP {exc.code}")
        except _RETRYABLE_TRANSPORT_ERRORS as exc:
            if attempt >= LLM_PROVIDER_RETRY_ATTEMPTS:
                logger.warning("LLM provider %s request failed: %s", operation_name, _safe_transport_error(exc))
                raise LLMCallError("LLM provider request failed") from exc
            _log_retry(operation_name, attempt, _safe_transport_error(exc))
        _sleep_before_retry(attempt)
    raise LLMCallError("LLM provider retry attempts exhausted")


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
            raise LLMInvalidResponseError("LLM provider stream returned invalid JSON") from exc
        if not isinstance(parsed, Mapping):
            raise LLMInvalidResponseError("LLM provider stream event must be a JSON object")

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


def _parse_responses_stream(response: Iterable[bytes]) -> Mapping[str, object]:
    latest_response: dict[str, object] | None = None
    latest_text: str | None = None
    pending_data: list[str] = []

    def flush_frame() -> None:
        nonlocal latest_response, latest_text, pending_data
        if not pending_data:
            return

        payload_text = "\n".join(pending_data).strip()
        pending_data = []
        if not payload_text or payload_text == "[DONE]":
            return

        try:
            parsed = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            raise LLMInvalidResponseError("LLM provider stream returned invalid JSON") from exc
        if not isinstance(parsed, Mapping):
            raise LLMInvalidResponseError("LLM provider stream event must be a JSON object")

        event_type = str(parsed.get("type", ""))
        maybe_response = parsed.get("response")
        if isinstance(maybe_response, Mapping):
            latest_response = dict(maybe_response)

        if event_type == "response.output_text.delta":
            delta = parsed.get("delta")
            if isinstance(delta, str):
                latest_text = (latest_text or "") + delta
        elif event_type == "response.output_text.done":
            text = parsed.get("text")
            if isinstance(text, str) and text.strip():
                latest_text = text.strip()
        elif event_type == "response.completed" and isinstance(maybe_response, Mapping):
            latest_response = dict(maybe_response)

    for raw_line in response:
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
    if latest_response is None:
        if latest_text is not None:
            return _response_from_text(latest_text, model="")
        raise LLMInvalidResponseError("LLM provider stream ended without a response")
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


def _has_message_content(provider_response: Mapping[str, object]) -> bool:
    try:
        _extract_message_content(provider_response)
    except LLMInvalidResponseError:
        return False
    return True


def _response_from_text(text: str, *, model: str) -> dict[str, object]:
    stripped = text.strip()
    if not stripped:
        raise LLMInvalidResponseError("LLM provider response has no message content")
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
    output = response.get("output")
    if isinstance(output, Sequence) and not isinstance(output, (str, bytes)):
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

    choices = response.get("choices")
    if isinstance(choices, Sequence) and not isinstance(choices, (str, bytes)) and choices:
        first_choice = choices[0]
        if isinstance(first_choice, Mapping):
            message = first_choice.get("message")
            if isinstance(message, Mapping):
                choice_content: object = message.get("content")
            else:
                choice_content = first_choice.get("text")
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

    raise LLMInvalidResponseError("LLM provider response has no message content")


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
        raise LLMInvalidResponseError("LLM message content is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise LLMInvalidResponseError("LLM message content must be a JSON object")
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
