import { useCallback, useEffect, useRef, useState } from "react";
import type { ApiError, CodeCompletionResult, NextAction, RuntimeStatus } from "../types";

export type SSEEventType = "agent_message" | "tool_status" | "runner_result" | "evaluation_result" | "done" | "error";

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
  | { type: "runner_result"; data: SSERunnerResult }
  | { type: "evaluation_result"; data: SSEEvaluationResult }
  | { type: "done"; data: SSEDone }
  | { type: "error"; data: SSEError };

export type SSEStatus = "idle" | "connecting" | "streaming" | "done" | "error";

type UseSSEOptions = {
  onEvent?: (event: SSEEvent) => void;
  onDone?: (data: SSEDone) => void;
  onError?: (error: ApiError) => void;
};

type UseSSEReturn = {
  events: SSEEvent[];
  status: SSEStatus;
  close: () => void;
};

/**
 * SSE hook framework. Currently not connected to real SSE endpoints
 * (backend has not implemented SSE yet). This hook is ready for
 * seamless integration once the backend supports text/event-stream.
 */
export function useSSE(endpoint: string | null, options: UseSSEOptions = {}): UseSSEReturn {
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [status, setStatus] = useState<SSEStatus>("idle");
  const sourceRef = useRef<EventSource | null>(null);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const close = useCallback(() => {
    if (sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!endpoint) {
      setStatus("idle");
      setEvents([]);
      return;
    }

    setStatus("connecting");
    setEvents([]);

    const source = new EventSource(endpoint);
    sourceRef.current = source;

    source.onopen = () => {
      setStatus("streaming");
    };

    const handleEvent = (type: SSEEventType) => (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        const event = { type, data } as SSEEvent;
        setEvents((prev) => [...prev, event]);
        optionsRef.current.onEvent?.(event);

        if (type === "done") {
          setStatus("done");
          optionsRef.current.onDone?.(data as SSEDone);
          source.close();
        }
        if (type === "error") {
          setStatus("error");
          optionsRef.current.onError?.((data as SSEError).error);
          source.close();
        }
      } catch {
        // Ignore malformed events
      }
    };

    source.addEventListener("agent_message", handleEvent("agent_message"));
    source.addEventListener("tool_status", handleEvent("tool_status"));
    source.addEventListener("runner_result", handleEvent("runner_result"));
    source.addEventListener("evaluation_result", handleEvent("evaluation_result"));
    source.addEventListener("done", handleEvent("done"));
    source.addEventListener("error", handleEvent("error"));

    source.onerror = () => {
      setStatus("error");
      source.close();
    };

    return () => {
      source.close();
      sourceRef.current = null;
    };
  }, [endpoint]);

  return { events, status, close };
}
