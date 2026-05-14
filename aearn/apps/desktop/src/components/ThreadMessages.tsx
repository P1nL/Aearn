import type { ConversationMessage } from "../appTypes";

export function ThreadMessages({ messages }: { messages: ConversationMessage[] }) {
  return (
    <>
      {messages.map((message) => (
        <article className={`message ${message.speaker}`} key={message.id}>
          <div className="avatar">{message.speaker === "agent" ? "A" : "你"}</div>
          <div className="bubble">
            {message.label && <div className="bubble-label">{message.label}</div>}
            {renderMessageBody(message.text)}
            {message.toolCard && <div className="tool-card">{message.toolCard}</div>}
          </div>
        </article>
      ))}
    </>
  );
}

function renderMessageBody(text: string) {
  return text.split("\n").map((line, index) => <p key={`${text}-${index}`}>{line}</p>);
}
