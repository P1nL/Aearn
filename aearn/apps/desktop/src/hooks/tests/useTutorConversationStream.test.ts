import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { parseTutorConversationFrame } from "../useTutorConversationStream";

describe("Tutor conversation SSE contract", () => {
  it("accepts an opaque signed cursor and the exact public event envelope", () => {
    const frame = [
      "id: opaque.cursor.signature",
      "event: control_updated",
      `data: ${JSON.stringify({
        event_id: "event-1", sequence: 7, kind: "control_updated", turn_id: null,
        item_id: null, item_kind: null, payload: { control_version: 3 },
        occurred_at: "2026-08-14T00:00:00+00:00", request_id: "request-1",
      })}`,
    ].join("\n");
    const parsed = parseTutorConversationFrame(frame);
    expect(parsed.kind).toBe("event");
    if (parsed.kind === "event") {
      expect(parsed.event.cursor).toBe("opaque.cursor.signature");
      expect(parsed.event.sequence).toBe(7);
      expect(parsed.event.kind).toBe("control_updated");
    }
  });

  it("accepts exact turn_output payloads and rejects protected or extra fields", () => {
    const event = {
      event_id: "event-output", sequence: 8, kind: "turn_output", turn_id: "turn-1",
      item_id: null, item_kind: null,
      payload: {
        output_version: "tutor_public_thinking_stream_v1", input_revision: 3,
        generation: 10001, operation: "append", chunk_sequence: 1, text: "先确认目标。",
      },
      occurred_at: "2026-08-15T00:00:00+00:00",
    };
    const exact = parseTutorConversationFrame([
      "id: opaque.output.cursor", "event: turn_output", `data: ${JSON.stringify(event)}`,
    ].join("\n"));
    expect(exact).toMatchObject({
      kind: "event",
      event: { kind: "turn_output", turn_id: "turn-1", payload: { operation: "append", text: "先确认目标。" } },
    });

    const protectedPayload = {
      ...event,
      payload: { ...event.payload, reasoning: "protected" },
    };
    expect(parseTutorConversationFrame([
      "id: opaque.output.cursor.2", "event: turn_output", `data: ${JSON.stringify(protectedPayload)}`,
    ].join("\n"))).toMatchObject({ kind: "error", resetRequired: true });

    const invalidComplete = {
      ...event,
      payload: { ...event.payload, operation: "complete", text: "not allowed" },
    };
    expect(parseTutorConversationFrame([
      "id: opaque.output.cursor.3", "event: turn_output", `data: ${JSON.stringify(invalidComplete)}`,
    ].join("\n"))).toMatchObject({ kind: "error", resetRequired: true });
  });

  it("requires a fresh snapshot for cursor and protocol failures", () => {
    const cursorError = parseTutorConversationFrame(`event: error\ndata: ${JSON.stringify({ error: {
      code: "CONVERSATION_CURSOR_INVALID", message: "refresh", details: {}, request_id: "request-2", recoverable: true,
    } })}`);
    expect(cursorError).toMatchObject({ kind: "error", resetRequired: true });
    expect(parseTutorConversationFrame("event: item_added\ndata: {}")).toMatchObject({ kind: "error", resetRequired: true });
  });

  it("keeps the main Desktop Tutor surface off retired run-local transports", () => {
    const source = readFileSync("src/features/tutor/TutorConversationSurface.tsx", "utf8");
    const api = readFileSync("src/api.ts", "utf8");
    expect(source).not.toContain("acceptTutorRunInput");
    expect(source).not.toContain("useTutorSSE");
    expect(source).not.toContain("buildTutorRunEventsUrl");
    expect(api).not.toContain("/api/tutor/runs/${encodeURIComponent(input.runId)}/inputs");
  });
});
