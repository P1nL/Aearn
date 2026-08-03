import { useCallback, useEffect, useRef, useState } from "react";

import type {
  ApiError,
  TutorSseEvent,
  TutorRunStatus,
  TutorTerminalOutcome,
} from "../types";

export type TutorSseStatus = "idle" | "connecting" | "streaming" | "reconnecting" | "done" | "error";

type UseTutorSSEOptions = {
  enabled?: boolean;
  maxReconnectAttempts?: number;
  onEvent?: (event: TutorSseEvent) => void;
  onError?: (error: ApiError) => void;
};

export type UseTutorSSEReturn = {
  events: TutorSseEvent[];
  status: TutorSseStatus;
  error: ApiError | null;
  cursor: number;
  retry: () => void;
  close: () => void;
};

const DEFAULT_MAX_RECONNECT_ATTEMPTS = 2;
const MAX_RETAINED_EVENTS = 100;
const MAX_SEEN_EVENT_IDS = 512;

/**
 * Consume one Tutor run's durable SSE suffix. The hook owns only transport
 * state: terminal run state stays server-authoritative through the public run
 * endpoint and durable terminal events.
 */
export function useTutorSSE(endpoint: string | null, options: UseTutorSSEOptions = {}): UseTutorSSEReturn {
  const [events, setEvents] = useState<TutorSseEvent[]>([]);
  const [status, setStatus] = useState<TutorSseStatus>("idle");
  const [error, setError] = useState<ApiError | null>(null);
  const [cursor, setCursor] = useState(0);
  const [retryVersion, setRetryVersion] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const streamKeyRef = useRef<string | null>(null);
  const cursorRef = useRef(0);
  const seenEventIdsRef = useRef<Set<number>>(new Set());
  const reconnectAttemptsRef = useRef(0);
  const manuallyClosedRef = useRef(false);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const close = useCallback(() => {
    manuallyClosedRef.current = true;
    abortRef.current?.abort();
    abortRef.current = null;
    setStatus((current) => (current === "done" || current === "error" ? current : "idle"));
  }, []);

  const retry = useCallback(() => {
    reconnectAttemptsRef.current = 0;
    manuallyClosedRef.current = false;
    setError(null);
    setRetryVersion((version) => version + 1);
  }, []);

  const enabled = options.enabled ?? true;
  const maxReconnectAttempts = options.maxReconnectAttempts ?? DEFAULT_MAX_RECONNECT_ATTEMPTS;

  useEffect(() => {
    if (!endpoint || !enabled) {
      streamKeyRef.current = null;
      cursorRef.current = 0;
      seenEventIdsRef.current.clear();
      reconnectAttemptsRef.current = 0;
      manuallyClosedRef.current = false;
      setEvents([]);
      setError(null);
      setCursor(0);
      setStatus("idle");
      return;
    }

    const isNewRun = streamKeyRef.current !== endpoint;
    if (isNewRun) {
      streamKeyRef.current = endpoint;
      cursorRef.current = 0;
      seenEventIdsRef.current.clear();
      reconnectAttemptsRef.current = 0;
      manuallyClosedRef.current = false;
      setEvents([]);
      setError(null);
      setCursor(0);
    }
    if (manuallyClosedRef.current) {
      return;
    }

    const controller = new AbortController();
    abortRef.current = controller;
    let retryTimer: number | null = null;
    let reachedTerminal = false;

    const emitTerminalError = (nextError: ApiError) => {
      reachedTerminal = true;
      setError(nextError);
      setStatus("error");
      optionsRef.current.onError?.(nextError);
      controller.abort();
    };

    const scheduleReconnect = (nextError: ApiError) => {
      if (controller.signal.aborted || manuallyClosedRef.current || reachedTerminal) {
        return;
      }
      if (reconnectAttemptsRef.current >= maxReconnectAttempts) {
        emitTerminalError(nextError);
        return;
      }
      reconnectAttemptsRef.current += 1;
      setError(nextError);
      setStatus("reconnecting");
      const delayMs = 250 * reconnectAttemptsRef.current;
      retryTimer = window.setTimeout(() => {
        if (!manuallyClosedRef.current) {
          setRetryVersion((version) => version + 1);
        }
      }, delayMs);
    };

    const dispatchEvent = (event: TutorSseEvent) => {
      if (event.id !== null) {
        if (event.id <= cursorRef.current || seenEventIdsRef.current.has(event.id)) {
          return;
        }
        cursorRef.current = event.id;
        seenEventIdsRef.current.add(event.id);
        if (seenEventIdsRef.current.size > MAX_SEEN_EVENT_IDS) {
          const oldest = seenEventIdsRef.current.values().next().value;
          if (typeof oldest === "number") {
            seenEventIdsRef.current.delete(oldest);
          }
        }
        setCursor(event.id);
      }

      setEvents((current) => [...current, event].slice(-MAX_RETAINED_EVENTS));
      optionsRef.current.onEvent?.(event);

      if (event.type === "done") {
        reachedTerminal = true;
        setError(null);
        setStatus("done");
        controller.abort();
        return;
      }
      if (event.type === "error") {
        reachedTerminal = true;
        setError(event.data.error);
        setStatus("error");
        optionsRef.current.onError?.(event.data.error);
        controller.abort();
      }
    };

    void (async () => {
      try {
        const headers: Record<string, string> = { Accept: "text/event-stream" };
        if (cursorRef.current > 0) {
          headers["Last-Event-ID"] = String(cursorRef.current);
        }
        setStatus(isNewRun || reconnectAttemptsRef.current === 0 ? "connecting" : "reconnecting");

        const response = await fetch(endpoint, {
          method: "GET",
          headers,
          signal: controller.signal,
        });
        if (!response.ok) {
          const responseError = await errorFromResponse(response);
          if (responseError.code === "SSE_CURSOR_INVALID") {
            emitTerminalError(responseError);
          } else {
            scheduleReconnect(responseError);
          }
          return;
        }
        if (!response.body) {
          scheduleReconnect(streamError("STREAM_UNAVAILABLE", "Tutor SSE 响应不包含可读取的数据流。"));
          return;
        }

        setStatus("streaming");
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (!controller.signal.aborted) {
          const { done, value } = await reader.read();
          if (done) {
            break;
          }
          buffer += decoder.decode(value, { stream: true });
          const drained = drainFrames(buffer);
          buffer = drained.rest;
          for (const frame of drained.frames) {
            const parsed = parseTutorSseFrame(frame);
            if (parsed.kind === "ignore") {
              continue;
            }
            if (parsed.kind === "error") {
              emitTerminalError(parsed.error);
              return;
            }
            dispatchEvent(parsed.event);
            if (reachedTerminal) {
              return;
            }
          }
        }

        buffer += decoder.decode();
        const drained = drainFrames(buffer);
        const remainingFrames = [...drained.frames, ...(drained.rest.trim() ? [drained.rest] : [])];
        for (const frame of remainingFrames) {
          const parsed = parseTutorSseFrame(frame);
          if (parsed.kind === "ignore") {
            continue;
          }
          if (parsed.kind === "error") {
            emitTerminalError(parsed.error);
            return;
          }
          dispatchEvent(parsed.event);
          if (reachedTerminal) {
            return;
          }
        }

        if (!reachedTerminal && !controller.signal.aborted) {
          scheduleReconnect(streamError("STREAM_INCOMPLETE", "Tutor 流在收到完成状态前中断。"));
        }
      } catch (caught) {
        if (!controller.signal.aborted && !manuallyClosedRef.current) {
          scheduleReconnect(
            streamError(
              "STREAM_ERROR",
              caught instanceof Error ? caught.message : "Tutor SSE 请求失败。",
            ),
          );
        }
      }
    })();

    return () => {
      if (retryTimer !== null) {
        window.clearTimeout(retryTimer);
      }
      controller.abort();
      if (abortRef.current === controller) {
        abortRef.current = null;
      }
    };
  }, [enabled, endpoint, maxReconnectAttempts, retryVersion]);

  return { events, status, error, cursor, retry, close };
}

type ParsedFrame =
  | { kind: "event"; event: TutorSseEvent }
  | { kind: "ignore" }
  | { kind: "error"; error: ApiError };

function drainFrames(buffer: string): { frames: string[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const parts = normalized.split("\n\n");
  return {
    frames: parts.slice(0, -1).filter((frame) => frame.trim().length > 0),
    rest: parts[parts.length - 1] ?? "",
  };
}

function parseTutorSseFrame(frame: string): ParsedFrame {
  let type: string | null = null;
  let rawId: string | null = null;
  const dataLines: string[] = [];

  for (const line of frame.split("\n")) {
    if (!line || line.startsWith(":")) {
      continue;
    }
    if (line.startsWith("event:")) {
      type = line.slice("event:".length).trim();
      continue;
    }
    if (line.startsWith("id:")) {
      rawId = line.slice("id:".length).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
  }

  if (!type && dataLines.length === 0) {
    return { kind: "ignore" };
  }
  if (!type || !isTutorEventType(type) || dataLines.length === 0) {
    return { kind: "error", error: streamError("TUTOR_SSE_PROTOCOL_ERROR", "Tutor SSE 返回了未知或不完整的事件。") };
  }

  const eventId = parseCursor(rawId);
  if (eventId === "invalid") {
    return { kind: "error", error: streamError("SSE_CURSOR_INVALID", "Tutor SSE 返回了无效的 run cursor。") };
  }
  if (type !== "error" && eventId === null) {
    return { kind: "error", error: streamError("TUTOR_SSE_PROTOCOL_ERROR", "Tutor SSE 事件缺少 run-local cursor。") };
  }

  try {
    const payload: unknown = JSON.parse(dataLines.join("\n"));
    const event = toTutorSseEvent(type, eventId, payload);
    if (!event) {
      return { kind: "error", error: streamError("TUTOR_SSE_PROTOCOL_ERROR", "Tutor SSE 事件不符合公开契约。") };
    }
    return { kind: "event", event };
  } catch {
    return { kind: "error", error: streamError("TUTOR_SSE_PROTOCOL_ERROR", "Tutor SSE 事件无法解析。") };
  }
}

function toTutorSseEvent(type: TutorSseEvent["type"], id: number | null, payload: unknown): TutorSseEvent | null {
  if (!isRecord(payload)) {
    return null;
  }

  if (type === "input_accepted") {
    if (id === null || !isEventBase(payload) || !isNullableString(payload.message_id) || payload.status !== "accepted") return null;
    return {
      id,
      type,
      data: {
        run_id: payload.run_id,
        input_revision: payload.input_revision,
        event_sequence: payload.event_sequence,
        message_id: payload.message_id,
        status: "accepted",
      },
    };
  }
  if (type === "tool_status") {
    if (id === null || !isEventBase(payload) || !isString(payload.status) || !isString(payload.tool) || !isString(payload.message)) return null;
    return {
      id,
      type,
      data: {
        run_id: payload.run_id,
        input_revision: payload.input_revision,
        event_sequence: payload.event_sequence,
        status: payload.status,
        tool: payload.tool,
        message: payload.message,
      },
    };
  }
  if (type === "activity") {
    if (id === null || !isEventBase(payload) || !isString(payload.category) || !isString(payload.status)) return null;
    return {
      id,
      type,
      data: {
        run_id: payload.run_id,
        input_revision: payload.input_revision,
        event_sequence: payload.event_sequence,
        category: payload.category,
        status: payload.status,
      },
    };
  }
  if (type === "run_state") {
    if (id === null || !isEventBase(payload) || !isTutorRunStatus(payload.status) || !isNullableTerminalOutcome(payload.terminal_outcome)) return null;
    if ("public_message" in payload && !isNullableString(payload.public_message)) return null;
    return {
      id,
      type,
      data: {
        run_id: payload.run_id,
        input_revision: payload.input_revision,
        event_sequence: payload.event_sequence,
        status: payload.status,
        terminal_outcome: payload.terminal_outcome,
        ...(typeof payload.public_message === "string" || payload.public_message === null
          ? { public_message: payload.public_message }
          : {}),
      },
    };
  }
  if (type === "done") {
    if (id === null || !isEventBase(payload) || !isRecord(payload.result_ref) || payload.result_ref.type !== "TutorRun" || !isString(payload.result_ref.id) || !isNullableString(payload.public_message)) return null;
    return {
      id,
      type,
      data: {
        run_id: payload.run_id,
        input_revision: payload.input_revision,
        event_sequence: payload.event_sequence,
        result_ref: { type: "TutorRun", id: payload.result_ref.id },
        public_message: payload.public_message,
      },
    };
  }
  if (!isApiError(payload.error)) {
    return null;
  }
  if ("public_message" in payload && !isNullableString(payload.public_message)) {
    return null;
  }
  return {
    id,
    type,
    data: {
      error: payload.error,
      ...(typeof payload.public_message === "string" || payload.public_message === null
        ? { public_message: payload.public_message }
        : {}),
    },
  };
}

function isEventBase(value: Record<string, unknown>): value is Record<string, unknown> & {
  run_id: string;
  input_revision: number;
  event_sequence: number;
} {
  return isString(value.run_id) && isNonNegativeSafeInteger(value.input_revision) && isNonNegativeSafeInteger(value.event_sequence);
}

function isTutorEventType(value: string): value is TutorSseEvent["type"] {
  return value === "input_accepted" || value === "tool_status" || value === "activity" || value === "run_state" || value === "done" || value === "error";
}

function parseCursor(value: string | null): number | null | "invalid" {
  if (value === null || value.length === 0) {
    return null;
  }
  if (!/^[0-9]+$/.test(value)) {
    return "invalid";
  }
  const parsed = Number(value);
  return isNonNegativeSafeInteger(parsed) ? parsed : "invalid";
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  try {
    const payload: unknown = await response.json();
    if (isRecord(payload) && isApiError(payload.error)) {
      return payload.error;
    }
  } catch {
    // A synthetic transport error below keeps the UI on a stable public shape.
  }
  return streamError("STREAM_HTTP_ERROR", `Tutor SSE 请求失败（HTTP ${response.status}）。`);
}

function streamError(code: string, message: string): ApiError {
  return {
    code,
    message,
    details: {},
    request_id: "tutor-sse-client",
    recoverable: true,
  };
}

function isTutorRunStatus(value: unknown): value is TutorRunStatus {
  return value === "queued" || value === "leased" || value === "running" || value === "waiting_for_input" || value === "waiting_for_capability" || value === "awaiting_effect_commit" || value === "completed" || value === "model_unavailable" || value === "blocked_policy" || value === "budget_exhausted" || value === "cancelled" || value === "failed";
}

function isNullableTerminalOutcome(value: unknown): value is TutorTerminalOutcome | null {
  return value === null || value === "completed" || value === "model_unavailable" || value === "blocked_policy" || value === "budget_exhausted" || value === "cancelled" || value === "failed";
}

function isApiError(value: unknown): value is ApiError {
  return isRecord(value) && isString(value.code) && isString(value.message) && isRecord(value.details) && isString(value.request_id) && typeof value.recoverable === "boolean";
}

function isNullableString(value: unknown): value is string | null {
  return isString(value) || value === null;
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isNonNegativeSafeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
