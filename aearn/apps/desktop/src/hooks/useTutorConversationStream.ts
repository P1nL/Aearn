import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiError, TutorTurnOutputPayload } from "../types";

export type TutorConversationEventKind =
  | "turn_created"
  | "turn_updated"
  | "item_added"
  | "item_updated"
  | "turn_output"
  | "control_updated"
  | "dispatch_delayed"
  | "dispatch_dead";

type TutorConversationEventBase = {
  cursor: string;
  event_id: string;
  sequence: number;
  turn_id: string | null;
  item_id: string | null;
  item_kind: string | null;
  occurred_at: string;
  request_id: string | null;
};

export type TutorConversationEvent =
  | (TutorConversationEventBase & { kind: "turn_output"; payload: TutorTurnOutputPayload })
  | (TutorConversationEventBase & {
      kind: Exclude<TutorConversationEventKind, "turn_output">;
      payload: Record<string, unknown>;
    });

export type TutorConversationStreamStatus = "idle" | "connecting" | "streaming" | "reconnecting" | "error";

type Options = {
  enabled?: boolean;
  initialCursor?: string | null;
  maxReconnectAttempts?: number;
  onEvent?: (event: TutorConversationEvent) => void;
  onResetRequired?: (error: ApiError) => void;
  onError?: (error: ApiError) => void;
};

export type TutorConversationStream = {
  status: TutorConversationStreamStatus;
  error: ApiError | null;
  cursor: string | null;
  retry: () => void;
  close: () => void;
};

const EVENT_KINDS = new Set<TutorConversationEventKind>([
  "turn_created", "turn_updated", "item_added", "item_updated", "turn_output", "control_updated", "dispatch_delayed", "dispatch_dead",
]);

export function useTutorConversationStream(endpoint: string | null, options: Options = {}): TutorConversationStream {
  const [status, setStatus] = useState<TutorConversationStreamStatus>("idle");
  const [error, setError] = useState<ApiError | null>(null);
  const [cursor, setCursor] = useState<string | null>(options.initialCursor ?? null);
  const [retryVersion, setRetryVersion] = useState(0);
  const cursorRef = useRef<string | null>(options.initialCursor ?? null);
  const sequenceRef = useRef<number | null>(null);
  const streamKeyRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const reconnectRef = useRef(0);
  const closedRef = useRef(false);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const close = useCallback(() => {
    closedRef.current = true;
    abortRef.current?.abort();
    setStatus("idle");
  }, []);

  const retry = useCallback(() => {
    reconnectRef.current = 0;
    closedRef.current = false;
    setError(null);
    setRetryVersion((value) => value + 1);
  }, []);

  const enabled = options.enabled ?? true;
  const maxReconnectAttempts = options.maxReconnectAttempts ?? 3;
  const initialCursor = options.initialCursor ?? null;

  useEffect(() => {
    if (!endpoint || !enabled) {
      abortRef.current?.abort();
      streamKeyRef.current = null;
      cursorRef.current = initialCursor;
      sequenceRef.current = null;
      reconnectRef.current = 0;
      closedRef.current = false;
      setCursor(initialCursor);
      setError(null);
      setStatus("idle");
      return;
    }

    const key = `${endpoint}\n${initialCursor ?? ""}`;
    if (streamKeyRef.current !== key) {
      streamKeyRef.current = key;
      cursorRef.current = initialCursor;
      sequenceRef.current = null;
      reconnectRef.current = 0;
      closedRef.current = false;
      setCursor(initialCursor);
      setError(null);
    }
    if (closedRef.current) return;

    const controller = new AbortController();
    abortRef.current = controller;
    let retryTimer: number | null = null;

    const requireSnapshot = (nextError: ApiError) => {
      setError(nextError);
      setStatus("error");
      optionsRef.current.onResetRequired?.(nextError);
      controller.abort();
    };
    const reconnect = (nextError: ApiError) => {
      if (controller.signal.aborted || closedRef.current) return;
      if (reconnectRef.current >= maxReconnectAttempts) {
        setError(nextError);
        setStatus("error");
        optionsRef.current.onError?.(nextError);
        return;
      }
      reconnectRef.current += 1;
      setError(nextError);
      setStatus("reconnecting");
      retryTimer = window.setTimeout(() => setRetryVersion((value) => value + 1), 250 * (2 ** (reconnectRef.current - 1)));
    };

    void (async () => {
      try {
        const headers: Record<string, string> = { Accept: "text/event-stream" };
        if (cursorRef.current) headers["Last-Event-ID"] = cursorRef.current;
        setStatus(reconnectRef.current > 0 ? "reconnecting" : "connecting");
        const response = await fetch(endpoint, { headers, signal: controller.signal });
        if (!response.ok) {
          const nextError = await errorFromResponse(response);
          if (nextError.code === "CONVERSATION_CURSOR_INVALID" || nextError.code === "SSE_CURSOR_INVALID") requireSnapshot(nextError);
          else reconnect(nextError);
          return;
        }
        if (!response.body) {
          reconnect(streamError("STREAM_UNAVAILABLE", "Tutor 对话流没有可读取的数据。"));
          return;
        }
        setStatus("streaming");
        setError(null);
        reconnectRef.current = 0;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (!controller.signal.aborted) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const drained = drainFrames(buffer);
          buffer = drained.rest;
          for (const frame of drained.frames) {
            const parsed = parseTutorConversationFrame(frame);
            if (parsed.kind === "ignore") continue;
            if (parsed.kind === "error") {
              if (parsed.resetRequired) requireSnapshot(parsed.error);
              else reconnect(parsed.error);
              return;
            }
            const previous = sequenceRef.current;
            if (previous !== null && parsed.event.sequence <= previous) continue;
            if (previous !== null && parsed.event.sequence > previous + 1) {
              requireSnapshot(streamError("CONVERSATION_EVENT_GAP", "Tutor 对话事件出现缺口，需要重新加载权威快照。"));
              return;
            }
            sequenceRef.current = parsed.event.sequence;
            cursorRef.current = parsed.event.cursor;
            setCursor(parsed.event.cursor);
            optionsRef.current.onEvent?.(parsed.event);
          }
        }
        if (!controller.signal.aborted) reconnect(streamError("STREAM_INCOMPLETE", "Tutor 对话流已中断，正在恢复连接。"));
      } catch (caught) {
        if (!controller.signal.aborted && !closedRef.current) {
          reconnect(streamError("STREAM_ERROR", caught instanceof Error ? caught.message : "Tutor 对话流连接失败。"));
        }
      }
    })();

    return () => {
      if (retryTimer !== null) window.clearTimeout(retryTimer);
      controller.abort();
      if (abortRef.current === controller) abortRef.current = null;
    };
  }, [enabled, endpoint, initialCursor, maxReconnectAttempts, retryVersion]);

  return { status, error, cursor, retry, close };
}

type ParsedFrame =
  | { kind: "event"; event: TutorConversationEvent }
  | { kind: "ignore" }
  | { kind: "error"; error: ApiError; resetRequired: boolean };

export function parseTutorConversationFrame(frame: string): ParsedFrame {
  let type: string | null = null;
  let cursor: string | null = null;
  const data: string[] = [];
  for (const line of frame.replace(/\r\n/g, "\n").split("\n")) {
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) type = line.slice(6).trim();
    else if (line.startsWith("id:")) cursor = line.slice(3).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (!type && data.length === 0) return { kind: "ignore" };
  if (type === "error") {
    try {
      const payload: unknown = JSON.parse(data.join("\n"));
      const error = isRecord(payload) && isApiError(payload.error) ? payload.error : streamError("TUTOR_SSE_PROTOCOL_ERROR", "Tutor 对话流返回了未知错误。");
      return { kind: "error", error, resetRequired: error.code === "CONVERSATION_CURSOR_INVALID" || error.code === "SSE_CURSOR_INVALID" };
    } catch {
      return { kind: "error", error: streamError("TUTOR_SSE_PROTOCOL_ERROR", "Tutor 对话流错误事件无法解析。"), resetRequired: true };
    }
  }
  if (!type || !EVENT_KINDS.has(type as TutorConversationEventKind) || !cursor || data.length === 0) {
    return { kind: "error", error: streamError("TUTOR_SSE_PROTOCOL_ERROR", "Tutor 对话流事件不完整。"), resetRequired: true };
  }
  try {
    const payload: unknown = JSON.parse(data.join("\n"));
    if (!isRecord(payload) || !isString(payload.event_id) || !isNonNegativeSafeInteger(payload.sequence) || payload.kind !== type ||
        !isNullableString(payload.turn_id) || !isNullableString(payload.item_id) || !isNullableString(payload.item_kind) ||
        !isRecord(payload.payload) || !isString(payload.occurred_at) || !(payload.request_id === undefined || isString(payload.request_id))) {
      return { kind: "error", error: streamError("TUTOR_SSE_PROTOCOL_ERROR", "Tutor 对话流事件不符合公开契约。"), resetRequired: true };
    }
    const base: TutorConversationEventBase = {
      cursor, event_id: payload.event_id, sequence: payload.sequence,
      turn_id: payload.turn_id, item_id: payload.item_id, item_kind: payload.item_kind,
      occurred_at: payload.occurred_at, request_id: payload.request_id ?? null,
    };
    if (type === "turn_output") {
      const output = toTutorTurnOutputPayload(payload.payload);
      if (!output || !payload.turn_id || payload.item_id !== null || payload.item_kind !== null) {
        return { kind: "error", error: streamError("TUTOR_SSE_PROTOCOL_ERROR", "Tutor 对话输出事件不符合公开契约。"), resetRequired: true };
      }
      return { kind: "event", event: { ...base, kind: "turn_output", payload: output } };
    }
    return { kind: "event", event: {
      ...base, kind: type as Exclude<TutorConversationEventKind, "turn_output">, payload: payload.payload,
    } };
  } catch {
    return { kind: "error", error: streamError("TUTOR_SSE_PROTOCOL_ERROR", "Tutor 对话流事件无法解析。"), resetRequired: true };
  }
}

function toTutorTurnOutputPayload(value: unknown): TutorTurnOutputPayload | null {
  if (!isRecord(value) || !isNonNegativeSafeInteger(value.input_revision) ||
      !isPositiveSafeInteger(value.generation) || !isNonNegativeSafeInteger(value.chunk_sequence) ||
      !isString(value.operation)) return null;
  if (value.output_version === "tutor_public_thinking_stream_v1") {
    if (value.operation === "append") {
      if (!hasExactKeys(value, ["output_version", "input_revision", "generation", "operation", "chunk_sequence", "text"]) ||
          value.chunk_sequence < 1 || !isString(value.text) || value.text.length < 1 || value.text.length > 160) return null;
      return {
        output_version: "tutor_public_thinking_stream_v1", input_revision: value.input_revision,
        generation: value.generation, operation: "append", chunk_sequence: value.chunk_sequence, text: value.text,
      };
    }
    if ((value.operation !== "reset" && value.operation !== "complete" && value.operation !== "discard") ||
        !hasExactKeys(value, ["output_version", "input_revision", "generation", "operation", "chunk_sequence"])) return null;
    return {
      output_version: "tutor_public_thinking_stream_v1", input_revision: value.input_revision,
      generation: value.generation, operation: value.operation, chunk_sequence: value.chunk_sequence,
    };
  }
  if (value.output_version !== "tutor_runtime_item_stream_v1" || !isString(value.item_id) ||
      (value.channel !== "reasoning" && value.channel !== "final_answer")) return null;
  if (value.operation === "append" || value.operation === "complete") {
    if (!hasExactKeys(value, ["output_version", "input_revision", "generation", "operation", "chunk_sequence", "item_id", "channel", "text"]) ||
        value.chunk_sequence < 1 || !isString(value.text) ||
        (value.operation === "append" && (value.text.length < 1 || value.text.length > 16_000)) ||
        (value.operation === "complete" && value.text.length > 1_000_000)) return null;
    return {
      output_version: "tutor_runtime_item_stream_v1", input_revision: value.input_revision,
      generation: value.generation, operation: value.operation, chunk_sequence: value.chunk_sequence,
      item_id: value.item_id, channel: value.channel, text: value.text,
    };
  }
  if ((value.operation !== "reset" && value.operation !== "discard") ||
      !hasExactKeys(value, ["output_version", "input_revision", "generation", "operation", "chunk_sequence", "item_id", "channel"])) return null;
  return {
    output_version: "tutor_runtime_item_stream_v1", input_revision: value.input_revision,
    generation: value.generation, operation: value.operation, chunk_sequence: value.chunk_sequence,
    item_id: value.item_id, channel: value.channel,
  };
}

function hasExactKeys(value: Record<string, unknown>, expected: string[]): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.length && expected.every((key) => keys.includes(key));
}
function isPositiveSafeInteger(value: unknown): value is number {
  return isNonNegativeSafeInteger(value) && value > 0;
}

function drainFrames(buffer: string): { frames: string[]; rest: string } {
  const parts = buffer.replace(/\r\n/g, "\n").split("\n\n");
  return { frames: parts.slice(0, -1).filter((part) => part.trim()), rest: parts.at(-1) ?? "" };
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  try {
    const payload: unknown = await response.json();
    if (isRecord(payload) && isApiError(payload.error)) return payload.error;
  } catch { /* use stable transport error */ }
  return streamError("STREAM_HTTP_ERROR", `Tutor 对话流请求失败（HTTP ${response.status}）。`);
}
function streamError(code: string, message: string): ApiError {
  return { code, message, details: {}, request_id: "tutor-conversation-sse-client", recoverable: true };
}
function isApiError(value: unknown): value is ApiError {
  return isRecord(value) && isString(value.code) && isString(value.message) && isRecord(value.details) && isString(value.request_id) && typeof value.recoverable === "boolean";
}
function isNullableString(value: unknown): value is string | null { return value === null || isString(value); }
function isString(value: unknown): value is string { return typeof value === "string"; }
function isNonNegativeSafeInteger(value: unknown): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= 0; }
function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
