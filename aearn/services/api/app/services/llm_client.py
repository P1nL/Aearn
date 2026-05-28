from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from collections.abc import Callable, Generator, Iterable, Mapping, Sequence
from dataclasses import dataclass

from app.core.config import Settings, get_settings


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
        return str(self._settings.openai_model)

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float = 0.2,
    ) -> LLMJsonResponse:
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
        headers = {
            "Authorization": f"Bearer {self._settings.openai_api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        provider_response = self._request_provider(payload, headers)
        content = _extract_message_content(provider_response)
        model = _response_model(provider_response) or self.model
        return LLMJsonResponse(content=_parse_json_object(content), model=model)

    def complete_text_stream(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float | None = None,
    ) -> Generator[str, None, str]:
        instructions, input_text = _messages_to_responses_input(messages)
        payload: dict[str, object] = {
            "model": self.model,
            "input": input_text,
            "stream": True,
        }
        if instructions is not None:
            payload["instructions"] = instructions
        if temperature is not None:
            payload["temperature"] = temperature
        headers = {
            "Authorization": f"Bearer {self._settings.openai_api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        url = _responses_url(str(self._settings.openai_base_url))
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
            return full_text
        except (LLMCallError, LLMInvalidResponseError):
            raise
        except Exception as exc:
            raise LLMCallError("LLM provider streaming transport failed") from exc

    def _request_provider(self, payload: Mapping[str, object], headers: Mapping[str, str]) -> Mapping[str, object]:
        url = _responses_url(str(self._settings.openai_base_url))
        timeout = float(self._settings.llm_timeout_seconds)
        if self._transport is not None:
            try:
                return self._transport(url, headers, payload, timeout)
            except (LLMCallError, LLMInvalidResponseError):
                raise
            except Exception as exc:
                raise LLMCallError("LLM provider transport failed") from exc
        return _post_json_stream(url, headers, payload, timeout)


def _responses_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1/responses") or normalized.endswith("/responses"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/responses"
    return f"{normalized}/v1/responses"


def _post_json_stream(
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, object],
    timeout: float,
) -> Mapping[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=dict(headers),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _parse_responses_stream(response)
    except urllib.error.HTTPError as exc:
        raise LLMCallError(f"LLM provider returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        raise LLMCallError("LLM provider request failed") from exc


def _post_text_stream(
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, object],
    timeout: float,
) -> Generator[str, None, None]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=dict(headers),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            yield from _iter_response_text_deltas(response)
    except urllib.error.HTTPError as exc:
        raise LLMCallError(f"LLM provider returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        raise LLMCallError("LLM provider request failed") from exc


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
                    deltas.append(str(delta["content"]))
                elif isinstance(choice.get("text"), str):
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
