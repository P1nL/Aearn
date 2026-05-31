from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import AsyncIterator, Callable, Iterable, Mapping, Sequence
from typing import Any, Protocol

from agents import Agent, InputGuardrail, ModelSettings, OutputGuardrail, RawResponsesStreamEvent, RunConfig, Tool
from agents.models.openai_provider import OpenAIProvider

from app.core.config import Settings
from app.services.llm_client import LLMCallError, LLMConfigurationError, LLMInvalidResponseError
from app.services.llm_urls import normalize_deepseek_base_url, normalize_openai_base_url


class AgentsSDKRunner(Protocol):
    def run_streamed(
        self,
        starting_agent: Agent[Any],
        input: str,
        context: object | None = None,
        max_turns: int | None = 10,
        hooks: object | None = None,
        run_config: RunConfig | None = None,
        previous_response_id: str | None = None,
        auto_previous_response_id: bool = False,
        conversation_id: str | None = None,
        session: object | None = None,
        *,
        error_handlers: object | None = None,
    ) -> object: ...


def build_run_config(settings: Settings) -> RunConfig:
    if not settings.openai_compatible_configured:
        raise LLMConfigurationError("OpenAI-compatible LLM settings are incomplete")

    if settings.llm_provider_type == "deepseek":
        base_url = normalize_deepseek_base_url(str(settings.llm_base_url))
        use_responses = False
    else:
        base_url = normalize_openai_base_url(str(settings.llm_base_url))
        use_responses = True

    provider = OpenAIProvider(
        api_key=str(settings.llm_api_key),
        base_url=base_url,
        use_responses=use_responses,
        strict_feature_validation=False,
    )
    return RunConfig(
        model=settings.llm_model,
        model_provider=provider,
        tracing_disabled=True,
        workflow_name="Aearn learning conversation",
    )


def build_agent(
    *,
    name: str,
    instructions: str,
    model: str,
    temperature: float | None,
    tools: Sequence[Tool] | None = None,
    handoffs: Sequence[Agent[Any]] | None = None,
    input_guardrails: Sequence[InputGuardrail[object]] | None = None,
    output_guardrails: Sequence[OutputGuardrail[object]] | None = None,
) -> Agent[object]:
    return Agent(
        name=name,
        instructions=instructions,
        tools=list(tools or []),
        handoffs=list(handoffs or []),
        model=model,
        model_settings=ModelSettings(temperature=temperature),
        input_guardrails=list(input_guardrails or []),
        output_guardrails=list(output_guardrails or []),
    )


def split_chat_messages(messages: Sequence[Mapping[str, str]]) -> tuple[str, str]:
    instructions: list[str] = []
    input_parts: list[str] = []

    for message in messages:
        role = str(message.get("role", "")).strip().lower()
        content = str(message.get("content", "")).strip()
        if not content:
            continue
        if role == "system":
            instructions.append(content)
        else:
            input_parts.append(content if role == "user" else f"{role}: {content}")

    input_text = "\n\n".join(input_parts).strip()
    if not input_text:
        raise LLMInvalidResponseError("Agents SDK request has no user content")

    combined_instructions = "\n\n".join(instructions).strip()
    if not combined_instructions:
        combined_instructions = "You are Aearn's programming-language learning agent."
    return combined_instructions, input_text


def iter_streamed_text(
    stream_factory: Callable[[], AsyncIterator[str]],
) -> Iterable[str]:
    output_queue: queue.Queue[str | BaseException | None] = queue.Queue()

    async def consume() -> None:
        async for delta in stream_factory():
            output_queue.put(delta)

    def worker() -> None:
        try:
            asyncio.run(consume())
        except BaseException as exc:
            output_queue.put(exc)
        finally:
            output_queue.put(None)

    thread = threading.Thread(target=worker, name="aearn-agents-sdk-stream", daemon=True)
    thread.start()

    while True:
        item = output_queue.get()
        if item is None:
            thread.join(timeout=0.1)
            return
        if isinstance(item, BaseException):
            thread.join(timeout=0.1)
            if isinstance(item, (LLMCallError, LLMConfigurationError, LLMInvalidResponseError)):
                raise item
            raise LLMCallError("OpenAI Agents SDK streaming failed") from item
        yield item


async def stream_text_deltas(
    *,
    runner: AgentsSDKRunner,
    agent: Agent[Any],
    input_text: str,
    run_config: RunConfig,
    max_turns: int = 4,
) -> AsyncIterator[str]:
    streamed = runner.run_streamed(
        agent,
        input_text,
        max_turns=max_turns,
        run_config=run_config,
    )

    emitted = False
    async for event in streamed.stream_events():  # type: ignore[attr-defined]
        delta = extract_text_delta(event, include_done_text=not emitted)
        if delta:
            emitted = True
            yield delta

    if not emitted:
        final_output = getattr(streamed, "final_output", None)
        if final_output is not None:
            text = str(final_output).strip()
            if text:
                yield text


def extract_text_delta(event: object, *, include_done_text: bool = True) -> str:
    data: object
    if isinstance(event, RawResponsesStreamEvent):
        data = event.data
    elif getattr(event, "type", None) == "raw_response_event":
        data = getattr(event, "data", None)
    else:
        return ""

    event_type = str(getattr(data, "type", "") or "")
    if event_type == "response.output_text.delta":
        delta = getattr(data, "delta", "")
        return delta if isinstance(delta, str) else ""
    if event_type == "response.output_text.done" and include_done_text:
        text = getattr(data, "text", "")
        return text if isinstance(text, str) else ""
    return ""
