import { type ReactNode, useEffect } from "react";
import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useComposerRuntime,
  useMessage,
  type ToolCallMessagePartProps,
} from "@assistant-ui/react";

import type { ConversationMessage } from "../appTypes";
import { useAssistantRuntime } from "../hooks/useAssistantRuntime";
import {
  CodeExerciseToolUI,
  ConceptCheckResultToolUI,
  ConceptIntroToolUI,
  LearningHistoryToolUI,
  LearningRouteRuntimeProvider,
  LearningRouteToolUI,
} from "./generative-ui/assistantToolUIs";

type AssistantUIThreadProps = {
  messages: ConversationMessage[];
  isStreaming: boolean;
  sessionActive: boolean;
  onSend: (text: string) => void;
  placeholder?: string;
  ariaLabel?: string;
  guidanceText?: string;
  emptyState?: ReactNode;
  beforeComposer?: ReactNode;
  composerPrefillText?: string | null;
  onComposerPrefillConsumed?: () => void;
  quickReplies?: string[];
  canOpenNoteDrawer?: boolean;
  noteDrawerOpen?: boolean;
  onToggleNoteDrawer?: () => void;
  hideNoteButton?: boolean;
};

/**
 * Headless assistant-ui thread wrapper.
 *
 * Reuses the existing CSS classes (`message`, `bubble`, `composer`) so the
 * visual shell stays consistent while message rendering is delegated to
 * assistant-ui primitives. Tool calls in `ConversationMessage.toolCalls`
 * surface as registered tool UI components (currently `show_learning_route`).
 */
export function AssistantUIThread({
  messages,
  isStreaming,
  sessionActive,
  onSend,
  placeholder,
  ariaLabel = "代码练习输入框",
  guidanceText,
  emptyState,
  beforeComposer,
  composerPrefillText,
  onComposerPrefillConsumed,
  quickReplies,
  canOpenNoteDrawer = false,
  noteDrawerOpen = false,
  onToggleNoteDrawer,
  hideNoteButton = true,
}: AssistantUIThreadProps) {
  const runtime = useAssistantRuntime({
    messages,
    isRunning: isStreaming,
    onSend,
  });

  const composerPlaceholder =
    placeholder ??
    (isStreaming
      ? "Agent 正在生成回答……"
      : !sessionActive
        ? "等待服务连接后即可对话。"
        : "向 AI 提问……");

  const composerDisabled = isStreaming || !sessionActive;
  const quickReplyEnabled = !composerDisabled && quickReplies && quickReplies.length > 0;
  const latestRouteToolCallId = findLatestRouteToolCallId(messages);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <LearningRouteRuntimeProvider latestToolCallId={latestRouteToolCallId}>
        <ComposerPrefillBridge text={composerPrefillText ?? null} onConsumed={onComposerPrefillConsumed} />
        <LearningRouteToolUI />
        <ConceptIntroToolUI />
        <ConceptCheckResultToolUI />
        <CodeExerciseToolUI />
        <LearningHistoryToolUI />
        <ThreadPrimitive.Root className="assistant-ui-thread">
          <ThreadPrimitive.Viewport autoScroll className="assistant-ui-thread-viewport">
            {messages.length === 0 && emptyState ? (
              <>{emptyState}</>
            ) : (
              <ThreadPrimitive.Messages>
                {() => <ConversationMessageRenderer source={messages} />}
              </ThreadPrimitive.Messages>
            )}
          </ThreadPrimitive.Viewport>

          {beforeComposer}

          <ComposerPrimitive.Root className="composer-wrap">
            {quickReplyEnabled && (
              <div className="quick-reply-chips" role="group" aria-label="快捷回复">
                {quickReplies.map((chip) => (
                  <button
                    className="quick-reply-chip"
                    key={chip}
                    type="button"
                    disabled={composerDisabled}
                    onClick={() => onSend(chip)}
                  >
                    {chip}
                  </button>
                ))}
              </div>
            )}
            <div className="composer">
              <ComposerPrimitive.Input
                aria-label={ariaLabel}
                placeholder={composerPlaceholder}
                disabled={composerDisabled}
                submitMode="enter"
                className="assistant-ui-composer-input"
              />
              {!hideNoteButton && onToggleNoteDrawer && (
                <button
                  className="btn primary send-btn note-inline-btn"
                  type="button"
                  aria-label={noteDrawerOpen ? "关闭知识点笔记" : "打开知识点笔记"}
                  aria-controls="noteDrawer"
                  aria-expanded={noteDrawerOpen}
                  disabled={!noteDrawerOpen && !canOpenNoteDrawer}
                  onClick={onToggleNoteDrawer}
                >
                  <img src="/note.png" alt="" />
                </button>
              )}
              <ComposerPrimitive.Send
                className="btn primary send-btn"
                aria-label="发送"
                disabled={composerDisabled}
              >
                ↑
              </ComposerPrimitive.Send>
            </div>
            {guidanceText && !sessionActive && (
              <div className="composer-guidance">{guidanceText}</div>
            )}
          </ComposerPrimitive.Root>
        </ThreadPrimitive.Root>
      </LearningRouteRuntimeProvider>
    </AssistantRuntimeProvider>
  );
}

function ComposerPrefillBridge({
  text,
  onConsumed,
}: {
  text: string | null;
  onConsumed?: () => void;
}) {
  const composer = useComposerRuntime({ optional: true });

  useEffect(() => {
    if (!text || !composer) return;
    const existing = composer.getState().text.trim();
    composer.setText(existing ? `${existing}\n\n${text}` : text);
    onConsumed?.();
    window.requestAnimationFrame(() => {
      document.querySelector<HTMLElement>(".assistant-ui-composer-input")?.focus();
    });
  }, [composer, onConsumed, text]);

  return null;
}

type RendererProps = {
  source: ConversationMessage[];
};

function ConversationMessageRenderer({ source }: RendererProps) {
  const message = useMessage();
  const original = source.find((entry) => entry.id === message.id);
  const speaker: "user" | "agent" = message.role === "user" ? "user" : "agent";
  const status = original?.status;

  return (
    <article
      className={messageClassName(speaker, status)}
      aria-live={status === "streaming" ? "polite" : undefined}
    >
      <div className="avatar">{speaker === "agent" ? "A" : "你"}</div>
      <div className="bubble">
        {original?.label && <div className="bubble-label">{original.label}</div>}
        <MessagePrimitive.Parts
          components={{
            Text: TextPart,
            tools: { Fallback: ToolCallFallback },
          }}
        />
        {original?.statusText && <div className="bubble-status">{original.statusText}</div>}
      </div>
    </article>
  );
}

function TextPart({ text, status }: { text: string; status: { type: string } }) {
  if (text.length === 0 && status.type !== "running") {
    return null;
  }
  const lines = text.split("\n");
  return (
    <>
      {lines.map((line, index) => (
        <p key={index}>
          {line}
          {status.type === "running" && index === lines.length - 1 && (
            <span className="stream-cursor" aria-hidden="true" />
          )}
        </p>
      ))}
    </>
  );
}

function ToolCallFallback({ toolName, status }: ToolCallMessagePartProps) {
  // Unknown tools render a small placeholder so the conversation stays readable.
  return (
    <div className="tool-card" aria-label={`工具调用 ${toolName}`}>
      正在调用 {toolName}{status.type === "running" ? "…" : ""}
    </div>
  );
}

function messageClassName(speaker: "agent" | "user", status?: ConversationMessage["status"]): string {
  return ["message", speaker, status].filter(Boolean).join(" ");
}

function findLatestRouteToolCallId(messages: ConversationMessage[]): string | null {
  for (let messageIndex = messages.length - 1; messageIndex >= 0; messageIndex -= 1) {
    const toolCalls = messages[messageIndex].toolCalls ?? [];
    for (let toolIndex = toolCalls.length - 1; toolIndex >= 0; toolIndex -= 1) {
      if (toolCalls[toolIndex].name === "show_learning_route") {
        return toolCalls[toolIndex].id;
      }
    }
  }
  return null;
}
