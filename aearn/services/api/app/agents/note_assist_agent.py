from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from app.agents.guardrails import assert_safe_teaching_output, build_teaching_guardrails
from app.agents.sdk_runtime import (
    AgentsSDKRunner,
    build_agent,
    build_run_config,
    iter_streamed_text,
    split_chat_messages,
    stream_text_deltas,
)
from app.core.config import Settings, get_settings
from app.services.llm_client import LLMCallError, LLMConfigurationError, LLMInvalidResponseError


NOTE_ASSIST_AGENT_NAME = "Aearn Note Assist"

_NOTE_REWRITE_PATTERNS = (
    re.compile(r"\bCodeDraft\b", re.IGNORECASE),
    re.compile(r"CodeDraftPage", re.IGNORECASE),
    re.compile(r"/api/code-drafts", re.IGNORECASE),
    re.compile(r"publishDrawer", re.IGNORECASE),
    re.compile(r"独立复盘草稿"),
    re.compile(r"面试讲述草稿"),
    re.compile(r"完整笔记"),
    re.compile(r"整篇笔记"),
    re.compile(r"重写整篇"),
    re.compile(r"完整替换"),
    re.compile(r"full note", re.IGNORECASE),
    re.compile(r"complete note", re.IGNORECASE),
    re.compile(r"rewrite (?:the )?(?:whole|entire) note", re.IGNORECASE),
)


@dataclass(frozen=True)
class NoteAssistContext:
    note_id: str
    note_title: str
    knowledge_point_title: str
    module_title: str
    language: str
    note_excerpt: str
    style: str
    focus: str
    session_id: str | None = None
    session_summary: str | None = None
    latest_attempt: Mapping[str, object] | None = None


class NoteAssistClient(Protocol):
    @property
    def model(self) -> str: ...

    def complete_text_stream(
        self,
        context: NoteAssistContext,
        *,
        temperature: float | None = 0.3,
    ) -> Iterable[str]: ...

    def complete_text(
        self,
        context: NoteAssistContext,
        *,
        temperature: float | None = 0.3,
    ) -> str | None: ...


class AgentsSDKNoteAssistClient:
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
        return str(self._settings.llm_model or "")

    def complete_text_stream(
        self,
        context: NoteAssistContext,
        *,
        temperature: float | None = 0.3,
    ) -> Iterable[str]:
        messages = _build_messages(context)
        instructions, input_text = split_chat_messages(messages)
        input_guardrails, output_guardrails = build_teaching_guardrails()
        agent = build_agent(
            name=NOTE_ASSIST_AGENT_NAME,
            instructions=instructions,
            model=self.model,
            temperature=temperature,
            tools=[],
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
                max_turns=2,
            )
        )

    def complete_text(
        self,
        context: NoteAssistContext,
        *,
        temperature: float | None = 0.3,
    ) -> str | None:
        chunks: list[str] = []
        try:
            for delta in self.complete_text_stream(context, temperature=temperature):
                if not delta:
                    continue
                assert_safe_note_draft_output(delta)
                chunks.append(delta)
        except (LLMCallError, LLMConfigurationError, LLMInvalidResponseError):
            return None

        text = "".join(chunks).strip()
        if not text:
            return None
        try:
            assert_safe_note_draft_output(text)
        except LLMInvalidResponseError:
            return None
        return text


def build_note_assist_client(
    settings: Settings | None = None,
    *,
    runner: AgentsSDKRunner | None = None,
) -> NoteAssistClient | None:
    effective_settings = settings or get_settings()
    if not effective_settings.openai_compatible_configured:
        return None
    try:
        return AgentsSDKNoteAssistClient(effective_settings, runner=runner)
    except LLMConfigurationError:
        return None


def assert_safe_note_draft_output(text: str) -> None:
    assert_safe_teaching_output(text)
    for pattern in _NOTE_REWRITE_PATTERNS:
        if pattern.search(text):
            raise LLMInvalidResponseError("Note Assist output leaked disallowed note-draft wording")


def _build_messages(context: NoteAssistContext) -> list[dict[str, str]]:
    evidence = {
        "learner_message": "继续补全当前笔记，只写可插入的补充片段，不要覆盖现有正文。",
        "task": "assist_note_draft",
        "style": context.style,
        "focus": context.focus,
        "note_summary": {
            "id": context.note_id,
            "title": context.note_title,
            "knowledge_point_title": context.knowledge_point_title,
            "module_title": context.module_title,
            "language": context.language,
            "excerpt": context.note_excerpt,
        },
        "session": {
            "id": context.session_id,
            "summary": context.session_summary,
        },
        "latest_attempt": _latest_attempt_evidence(context.latest_attempt),
        "output_schema": {
            "content": "insertable supplement text only",
        },
    }
    return [
        {
            "role": "system",
            "content": (
                "你是 Aearn 的笔记辅助补全 Agent。只输出可以直接插入 Note.agent_draft_content 的补充片段，"
                "不要覆盖现有正文，不要生成独立 CodeDraft，不要泄露 provider、隐藏测试或参考答案。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
        },
    ]


def _latest_attempt_evidence(latest_attempt: Mapping[str, object] | None) -> dict[str, object]:
    if latest_attempt is None:
        return {"available": False}

    return {
        "available": True,
        "attempt_id": _bounded_text(latest_attempt.get("attempt_id"), 80),
        "session_id": _bounded_text(latest_attempt.get("session_id"), 80),
        "attempt_type": _bounded_text(latest_attempt.get("attempt_type"), 40),
        "runtime_status": _bounded_text(latest_attempt.get("runtime_status"), 60),
        "test_pass_rate": latest_attempt.get("test_pass_rate"),
        "passed_test_count": latest_attempt.get("passed_test_count"),
        "total_test_count": latest_attempt.get("total_test_count"),
        "error_message": _bounded_text(latest_attempt.get("error_message"), 360),
        "error_cause": _bounded_text(latest_attempt.get("error_cause"), 120),
        "explanation_text": _bounded_text(latest_attempt.get("explanation_text"), 240),
        "hint_usage_count": latest_attempt.get("hint_usage_count"),
        "error_count": latest_attempt.get("error_count"),
    }


def _bounded_text(value: object, max_length: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}..."
