import { afterEach, expect, it, vi } from "vitest";
import { fetchTutorConversationSnapshot } from "../api";

const error = { kind: "error", id: "terminal-error-1", turn_id: "turn-1", code: "CAPABILITY_DENIED",
  message: "Tutor 未能安全完成本轮处理。请调整问题后发送一条新消息。", recoverable: false, created_at: "2026-09-08T00:00:00Z" };
const snapshot = { snapshot_version: "tutor_conversation_snapshot_v2",
  conversation: { conversation_id: "conversation-1", title: "测试", control_version: 1, control_state: "idle",
    queue_paused: false, queue_pause_reason: null, pending_count: 0, max_pending: 10 },
  active_turn: null, active_thinking: null, pending_requests: [], queue: [], timeline: [error],
  next_cursor: null, has_more: false, stream_cursor: "opaque.cursor" };
const fetchSnapshot = () => fetchTutorConversationSnapshot({ userId: "user-1", conversationId: "conversation-1", limit: 40 });
function respond(item: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ...snapshot, timeline: [item] }), {
    status: 200, headers: { "Content-Type": "application/json" },
  })));
}
afterEach(() => vi.unstubAllGlobals());
it.each([false, true])("preserves the server error identity, Chinese copy and recoverability (%s)", async (recoverable) => {
  respond({ ...error, recoverable });
  const first = await fetchSnapshot();
  const reconnected = await fetchSnapshot();
  expect(first.timeline).toEqual([{ ...error, recoverable }]);
  expect(reconnected.timeline).toEqual(first.timeline);
});
it.each([{ diagnostic_code: "unknown_capability" }, { provider_payload: "private" }, { recoverable: "true" }])(
  "rejects private fields or malformed authority %j", async (extra) => {
    respond({ ...error, ...extra });
    await expect(fetchSnapshot()).rejects.toThrow();
  },
);
