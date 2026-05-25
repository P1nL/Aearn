import { useMemo } from "react";
import {
  useExternalStoreRuntime,
  type ExternalStoreAdapter,
  type ThreadMessageLike,
} from "@assistant-ui/react";

import type { ConversationMessage } from "../appTypes";

type UseAssistantRuntimeOptions = {
  messages: ConversationMessage[];
  isRunning: boolean;
  onSend: (text: string) => void;
};

/**
 * Bridges the existing Zustand `ConversationMessage[]` slice into an
 * assistant-ui external store runtime.
 *
 * Maps the existing message shape to `ThreadMessageLike` so plain text and
 * generative-ui tool calls render through the assistant-ui primitives while
 * Zustand stays the source of truth.
 */
export function useAssistantRuntime({
  messages,
  isRunning,
  onSend,
}: UseAssistantRuntimeOptions) {
  const adapter = useMemo<ExternalStoreAdapter<ConversationMessage>>(
    () => ({
      messages,
      isRunning,
      convertMessage: convertConversationMessage,
      onNew: async (message) => {
        const text = extractTextFromAppendMessage(message);
        if (text.trim().length === 0) {
          return;
        }
        onSend(text);
      },
    }),
    [messages, isRunning, onSend],
  );

  return useExternalStoreRuntime(adapter);
}

function convertConversationMessage(message: ConversationMessage): ThreadMessageLike {
  if (message.speaker === "user") {
    return {
      role: "user",
      id: message.id,
      content: [{ type: "text", text: message.text }],
    };
  }

  const content: ThreadMessageLike["content"] = buildAssistantContent(message);
  const status = mapAssistantStatus(message.status);

  return {
    role: "assistant",
    id: message.id,
    content,
    status,
  };
}

function buildAssistantContent(message: ConversationMessage): ThreadMessageLike["content"] {
  const parts: Array<{ type: string; [key: string]: unknown }> = [];

  if (message.text.length > 0) {
    parts.push({ type: "text", text: message.text });
  } else if (message.status === "streaming" && (!message.toolCalls || message.toolCalls.length === 0)) {
    parts.push({ type: "text", text: "" });
  }

  for (const toolCall of message.toolCalls ?? []) {
    parts.push({
      type: "tool-call",
      toolCallId: toolCall.id,
      toolName: toolCall.name,
      args: isRecord(toolCall.args) ? (toolCall.args as Record<string, unknown>) : undefined,
      argsText: toolCall.argsBuffer,
    });
  }

  if (parts.length === 0) {
    parts.push({ type: "text", text: "" });
  }

  return parts as unknown as ThreadMessageLike["content"];
}

function mapAssistantStatus(status: ConversationMessage["status"]): ThreadMessageLike["status"] {
  switch (status) {
    case "streaming":
      return { type: "running" } as const;
    case "error":
      return { type: "incomplete", reason: "error" } as const;
    case "done":
      return { type: "complete", reason: "stop" } as const;
    default:
      return undefined;
  }
}

function extractTextFromAppendMessage(message: { content: unknown }): string {
  if (!Array.isArray(message.content)) {
    return "";
  }
  const segments: string[] = [];
  for (const part of message.content) {
    if (isRecord(part) && part.type === "text" && typeof part.text === "string") {
      segments.push(part.text);
    }
  }
  return segments.join("");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
