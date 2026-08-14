import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchTutorConversationSnapshot, fetchTutorThreadTurnV2Capability } from "../api";

afterEach(() => vi.unstubAllGlobals());

describe("Tutor v2 API boundary", () => {
  it("accepts backend active turns that omit nullable optional fields", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      snapshot_version: "tutor_conversation_snapshot_v1",
      conversation: { conversation_id: "conversation-1", title: "测试", control_version: 2, control_state: "running", queue_paused: false, queue_pause_reason: null, pending_count: 0, max_pending: 10 },
      active_turn: { turn_id: "turn-1", conversation_id: "conversation-1", interaction_protocol_version: "thread_turn_v2", status: "in_progress", input_revision: 3, created_at: "2026-08-14T00:00:00Z", updated_at: "2026-08-14T00:00:01Z" },
      pending_requests: [], queue: [], timeline: [], next_cursor: null, has_more: false, stream_cursor: "opaque.cursor",
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    const snapshot = await fetchTutorConversationSnapshot({ userId: "user-1", conversationId: "conversation-1" });
    expect(snapshot.active_turn).toMatchObject({ input_revision: 3, retry_of_turn_id: null, retry_root_turn_id: null, completion_reason: null });
  });

  it("routes capability bootstrap to the API origin", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      schema_version: "tutor_thread_turn_v2_capability_v1", cutover_version: "tutor_thread_turn_v2_global_v1", desktop_contract_version: "tutor_thread_turn_v2_desktop_v1",
      env_allowed: true, state: "enabled", generation: 1, summary_hash: "0".repeat(64), block_code: null, effective_enabled: true, counts: {}, prepared_at: null, enabled_at: "2026-08-14T00:00:00Z", updated_at: "2026-08-14T00:00:00Z",
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    await fetchTutorThreadTurnV2Capability("user-1");
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("http://127.0.0.1:8001/api/tutor/capabilities/thread-turn-v2?user_id=user-1");
  });
});
