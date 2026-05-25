import { type ReactNode } from "react";
import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useMessage,
  type ToolCallMessagePartProps,
} from "@assistant-ui/react";

import type { ConversationMessage } from "../appTypes";
import { useAssistantRuntime } from "../hooks/useAssistantRuntime";
import { LearningRouteToolUI } from "./generative-ui/assistantToolUIs";

type AssistantUIThreadProps = {
  messages: ConversationMessage[];
  isStreaming: boolean;
  sessionActive: boolean;
  onSend: (text: string) => void;
  placeholder?: string;
  ariaLabel?: string;
  guidanceText?: string;
  emptyState?: ReactNode;
  /** Render a side card after a specific message (e.g., InlinePlanCard). */
  renderInlineCard?: (message: ConversationMessage) => ReactNode | null;
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
  renderInlineCard,
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

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <LearningRouteToolUI />
      <ThreadPrimitive.Root className="assistant-ui-thread">
        <ThreadPrimitive.Viewport autoScroll className="assistant-ui-thread-viewport">
          {messages.length === 0 && emptyState ? (
            <>{emptyState}</>
          ) : (
            <ThreadPrimitive.Messages>
              {() => (
                <ConversationMessageRenderer
                  source={messages}
                  renderInlineCard={renderInlineCard}
                />
              )}
            </ThreadPrimitive.Messages>
          )}
        </ThreadPrimitive.Viewport>

        <ComposerPrimitive.Root className="composer-wrap">
          <div className="composer">
            <ComposerPrimitive.Input
              aria-label={ariaLabel}
              placeholder={composerPlaceholder}
              disabled={composerDisabled}
              submitMode="enter"
              className="assistant-ui-composer-input"
            />
            <ComposerPrimitive.Send
              className="btn primary send-btn"
              aria-label="发送"
            >
              ↑
            </ComposerPrimitive.Send>
          </div>
          {guidanceText && !sessionActive && (
            <div className="composer-guidance">{guidanceText}</div>
          )}
        </ComposerPrimitive.Root>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}

type RendererProps = {
  source: ConversationMessage[];
  renderInlineCard?: (message: ConversationMessage) => ReactNode | null;
};

function ConversationMessageRenderer({ source, renderInlineCard }: RendererProps) {
  const message = useMessage();
  const original = source.find((entry) => entry.id === message.id);
  const speaker: "user" | "agent" = message.role === "user" ? "user" : "agent";
  const status = original?.status;
  const inlineCard = original && renderInlineCard ? renderInlineCard(original) : null;

  return (
    <>
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
      {inlineCard}
    </>
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
