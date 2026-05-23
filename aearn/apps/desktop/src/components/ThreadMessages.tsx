import type { ConversationMessage } from "../appTypes";

export function ThreadMessages({ messages }: { messages: ConversationMessage[] }) {
  return (
    <>
      {messages.map((message) => (
        <article className={messageClassName(message)} key={message.id}>
          <div className="avatar">{message.speaker === "agent" ? "A" : "你"}</div>
          <div className="bubble">
            {message.label && <div className="bubble-label">{message.label}</div>}
            {renderMessageBody(message)}
            {message.toolCard && <div className="tool-card">{message.toolCard}</div>}
            {message.statusText && <div className="bubble-status">{message.statusText}</div>}
          </div>
        </article>
      ))}
    </>
  );
}

function messageClassName(message: ConversationMessage): string {
  return ["message", message.speaker, message.status].filter(Boolean).join(" ");
}

function renderMessageBody(message: ConversationMessage) {
  const text = message.text || (message.status === "streaming" ? "正在生成回答" : "");
  return text.split("\n").map((line, index) => (
    <p key={`${message.id}-${index}`}>
      {line}
      {message.status === "streaming" && index === text.split("\n").length - 1 && (
        <span className="stream-cursor" aria-hidden="true" />
      )}
    </p>
  ));
}
