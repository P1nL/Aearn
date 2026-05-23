from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import cast

from app.agents.guardrails import build_teaching_guardrails
from app.agents.sdk_runtime import (
    AgentsSDKRunner,
    build_agent,
    build_run_config,
    iter_streamed_text,
    split_chat_messages,
    stream_text_deltas,
)
from app.agents.tools import build_teaching_tools
from app.core.config import Settings


TEACHING_AGENT_NAME = "Aearn Teaching Agent"


class AgentsSDKLearningConversationClient:
    def __init__(
        self,
        settings: Settings,
        *,
        runner: AgentsSDKRunner | None = None,
    ) -> None:
        self._settings = settings
        self._run_config = build_run_config(settings)
        self._runner = runner

    @property
    def model(self) -> str:
        return str(self._settings.openai_model or "")

    def complete_text_stream(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float | None = None,
    ) -> Iterable[str]:
        instructions, input_text = split_chat_messages(messages)
        input_guardrails, output_guardrails = build_teaching_guardrails()
        agent = build_agent(
            name=TEACHING_AGENT_NAME,
            instructions=instructions,
            model=self.model,
            temperature=temperature,
            tools=build_teaching_tools(messages),
            input_guardrails=input_guardrails,
            output_guardrails=output_guardrails,
        )
        runner = self._runner
        if runner is None:
            from agents import Runner

            runner = cast(AgentsSDKRunner, Runner)

        return iter_streamed_text(
            lambda: stream_text_deltas(
                runner=runner,
                agent=agent,
                input_text=input_text,
                run_config=self._run_config,
            )
        )
