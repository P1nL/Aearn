import type { ConversationMessage } from "../appTypes";

type AssistantThreadProps = {
  messages: ConversationMessage[];
  emptyState?: React.ReactNode;
  renderInlineCard?: (message: ConversationMessage) => React.ReactNode | null;
};

/**
 * Assistant-ui-compatible thread renderer.
 *
 * Renders a list of ConversationMessage items as an assistant-style thread.
 * Streaming messages show a cursor on the last line. Empty state is explicit
 * and provided by the parent.
 *
 * The optional `renderInlineCard` prop allows parent pages to inject
 * inline card components (e.g., InlinePlanCard) after specific messages
 * based on message metadata.
 */
export function AssistantThread({ messages, emptyState, renderInlineCard }: AssistantThreadProps) {
  if (messages.length === 0 && emptyState) {
    return <>{emptyState}</>;
  }

  return (
    <>
      {messages.map((message) => (
        <div key={message.id}>
          <article className={threadMessageClassName(message)} aria-live={message.status === "streaming" ? "polite" : undefined}>
            <div className="avatar">{message.speaker === "agent" ? "A" : "你"}</div>
            <div className="bubble">
              {message.label && <div className="bubble-label">{message.label}</div>}
              <AssistantMessageBody message={message} />
              {message.toolCard && <div className="tool-card">{message.toolCard}</div>}
              {message.statusText && <div className="bubble-status">{message.statusText}</div>}
            </div>
          </article>
          {renderInlineCard?.(message)}
        </div>
      ))}
    </>
  );
}

function AssistantMessageBody({ message }: { message: ConversationMessage }) {
  const text = message.text || (message.status === "streaming" ? "正在生成回答" : "");
  const lines = text.split("\n");

  return (
    <>
      {lines.map((line, index) => (
        <p key={`${message.id}-${index}`}>
          {line}
          {message.status === "streaming" && index === lines.length - 1 && (
            <span className="stream-cursor" aria-hidden="true" />
          )}
        </p>
      ))}
    </>
  );
}

function threadMessageClassName(message: ConversationMessage): string {
  return ["message", message.speaker, message.status].filter(Boolean).join(" ");
}
