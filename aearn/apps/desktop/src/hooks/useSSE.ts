import { useCallback, useEffect, useRef, useState } from "react";
import type { ApiError, CodeCompletionResult, NextAction, RuntimeStatus } from "../types";

export type SSEEventType =
  | "agent_message"
  | "tool_status"
  | "tool_call"
  | "runner_result"
  | "evaluation_result"
  | "plan_draft"
  | "session_created"
  | "done"
  | "error";

export type SSESessionCreated = {
  request_id: string;
  onboarding_session_id: string;
};

export type SSEAgentMessage = {
  request_id: string;
  session_id: string;
  message_id: string;
  delta: string;
  content: string;
  next_action: NextAction;
};

export type SSEToolStatus = {
  request_id: string;
  session_id: string;
  node: string;
  tool: string;
  status: "running" | "completed" | "failed";
  message: string;
};

export type SSERunnerResult = {
  request_id: string;
  session_id: string;
  attempt_id: string;
  runtime_status: RuntimeStatus;
  preview_url: string | null;
  stdout: string;
  stderr: string;
  test_pass_rate: number;
  test_results: Array<{
    case_id: string;
    case_type: string;
    passed: boolean;
    weight: number;
    message: string;
  }>;
  next_action: NextAction;
};

export type SSEEvaluationResult = {
  request_id: string;
  session_id: string;
  attempt_id: string;
  code_completion_result: CodeCompletionResult;
};

export type SSEPlanDraft = {
  request_id: string;
  session_id: string;
  draft_id: string;
  modules: Array<{ title: string; knowledge_points: Array<{ title: string; id: string }> }>;
  summary: string;
};

export type SSEToolCallStart = {
  phase: "start";
  tool_call_id: string;
  name: string;
};

export type SSEToolCallDelta = {
  phase: "delta";
  tool_call_id: string;
  arguments_delta: string;
};

export type SSEToolCallDone = {
  phase: "done";
  tool_call_id: string;
  arguments: unknown;
};

export type SSEToolCall = SSEToolCallStart | SSEToolCallDelta | SSEToolCallDone;

export type SSEDone = {
  request_id: string;
  session_id: string;
  result_ref: {
    type: string;
    id: string;
  };
};

export type SSEError = {
  error: ApiError;
};

export type SSEEvent =
  | { type: "agent_message"; data: SSEAgentMessage }
  | { type: "tool_status"; data: SSEToolStatus }
  | { type: "tool_call"; data: SSEToolCall }
  | { type: "runner_result"; data: SSERunnerResult }
  | { type: "evaluation_result"; data: SSEEvaluationResult }
  | { type: "plan_draft"; data: SSEPlanDraft }
  | { type: "session_created"; data: SSESessionCreated }
  | { type: "done"; data: SSEDone }
  | { type: "error"; data: SSEError };

export type SSEStatus = "idle" | "connecting" | "streaming" | "done" | "error";

type UseSSEOptions = {
  method?: "GET" | "POST";
  body?: unknown;
  headers?: Record<string, string>;
  requestId?: string;
  onEvent?: (event: SSEEvent) => void;
  onDone?: (data: SSEDone) => void;
  onError?: (error: ApiError) => void;
};

type UseSSEReturn = {
  events: SSEEvent[];
  status: SSEStatus;
  close: () => void;
};

export function useSSE(endpoint: string | null, options: UseSSEOptions = {}): UseSSEReturn {
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [status, setStatus] = useState<SSEStatus>("idle");
  const abortRef = useRef<AbortController | null>(null);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const requestBody = options.body === undefined ? undefined : JSON.stringify(options.body);
  const requestHeaders = JSON.stringify(options.headers ?? {});
  const method = options.method ?? (requestBody === undefined ? "GET" : "POST");
  const requestId = options.requestId;

  const close = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  useEffect(() => {
    if (!endpoint) {
      setStatus("idle");
      setEvents([]);
      return;
    }

    setStatus("connecting");
    setEvents([]);

    const controller = new AbortController();
    const effectiveRequestId = requestId ?? `desktop-${Date.now()}`;
    abortRef.current = controller;
    let sawTerminalEvent = false;

    const emitError = (error: ApiError) => {
      sawTerminalEvent = true;
      setStatus("error");
      optionsRef.current.onError?.(error);
      controller.abort();
    };

    const dispatchEvent = (event: SSEEvent) => {
      setEvents((prev) => [...prev, event]);
      optionsRef.current.onEvent?.(event);
      if (event.type === "done") {
        sawTerminalEvent = true;
        setStatus("done");
        optionsRef.current.onDone?.(event.data);
        controller.abort();
      } else if (event.type === "error") {
        emitError(event.data.error);
      }
    };

    void (async () => {
      try {
        const response = await fetch(endpoint, {
          method,
          body: requestBody,
          headers: {
            Accept: "text/event-stream",
            "Content-Type": "application/json",
            "X-Request-Id": effectiveRequestId,
            ...JSON.parse(requestHeaders),
          },
          signal: controller.signal,
        });

        if (!response.ok) {
          emitError(await errorFromResponse(response, effectiveRequestId));
          return;
        }
        if (!response.body) {
          emitError(streamError("STREAM_UNAVAILABLE", "SSE response has no readable body", effectiveRequestId));
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
            const event = parseSSEFrame(frame);
            if (event) {
              dispatchEvent(event);
            }
          }
        }

        buffer += decoder.decode();
        const drained = drainFrames(buffer);
        for (const frame of drained.frames.concat(drained.rest ? [drained.rest] : [])) {
          const event = parseSSEFrame(frame);
          if (event) {
            dispatchEvent(event);
          }
        }

        if (!sawTerminalEvent && !controller.signal.aborted) {
          emitError(streamError("STREAM_INCOMPLETE", "SSE stream ended without done or error", effectiveRequestId));
        }
      } catch (error) {
        if (controller.signal.aborted) {
          return;
        }
        emitError(streamError("STREAM_ERROR", error instanceof Error ? error.message : "SSE request failed", effectiveRequestId));
      }
    })();

    return () => {
      controller.abort();
      if (abortRef.current === controller) {
        abortRef.current = null;
      }
    };
  }, [endpoint, method, requestBody, requestHeaders, requestId]);

  return { events, status, close };
}

function drainFrames(buffer: string): { frames: string[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const parts = normalized.split("\n\n");
  return {
    frames: parts.slice(0, -1).filter((frame) => frame.trim().length > 0),
    rest: parts[parts.length - 1] ?? "",
  };
}

function parseSSEFrame(frame: string): SSEEvent | null {
  let type: SSEEventType | null = null;
  const dataLines: string[] = [];

  for (const line of frame.split("\n")) {
    if (line.startsWith(":")) {
      continue;
    }
    if (line.startsWith("event:")) {
      const eventType = line.slice("event:".length).trim();
      if (isSSEEventType(eventType)) {
        type = eventType;
      }
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
  }

  if (!type || dataLines.length === 0) {
    return null;
  }

  try {
    const data: unknown = JSON.parse(dataLines.join("\n"));
    return toTypedSSEEvent(type, data);
  } catch {
    return null;
  }
}

function toTypedSSEEvent(type: SSEEventType, data: unknown): SSEEvent | null {
  if (!isRecord(data)) {
    return null;
  }
  switch (type) {
    case "agent_message":
      return { type, data: data as SSEAgentMessage };
    case "tool_status":
      return { type, data: data as SSEToolStatus };
    case "tool_call": {
      const phase = data.phase;
      if (phase !== "start" && phase !== "delta" && phase !== "done") return null;
      if (typeof data.tool_call_id !== "string") return null;
      return { type, data: data as SSEToolCall };
    }
    case "runner_result":
      return { type, data: data as SSERunnerResult };
    case "evaluation_result":
      return { type, data: data as SSEEvaluationResult };
    case "plan_draft":
      return { type, data: data as SSEPlanDraft };
    case "session_created":
      return { type, data: data as SSESessionCreated };
    case "done":
      return { type, data: data as SSEDone };
    case "error":
      return isRecord(data.error) ? { type, data: data as SSEError } : null;
  }
}

async function errorFromResponse(response: Response, requestId: string): Promise<ApiError> {
  try {
    const payload: unknown = await response.json();
    if (isRecord(payload) && isRecord(payload.error) && typeof payload.error.code === "string") {
      return payload.error as ApiError;
    }
  } catch {
    // Fall back to a synthetic stream error below.
  }
  return streamError("STREAM_HTTP_ERROR", `SSE request failed with status ${response.status}`, requestId);
}

function streamError(code: string, message: string, requestId: string): ApiError {
  return {
    code,
    message,
    details: {},
    request_id: requestId,
    recoverable: true,
  };
}

function isSSEEventType(value: string): value is SSEEventType {
  return (
    value === "agent_message" ||
    value === "tool_status" ||
    value === "tool_call" ||
    value === "runner_result" ||
    value === "evaluation_result" ||
    value === "plan_draft" ||
    value === "session_created" ||
    value === "done" ||
    value === "error"
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
