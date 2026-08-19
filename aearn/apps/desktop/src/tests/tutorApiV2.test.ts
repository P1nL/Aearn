import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchTutorConversationSnapshot, fetchTutorThreadTurnV2Capability } from "../api";

afterEach(() => vi.unstubAllGlobals());

describe("Tutor v2 API boundary", () => {
  it("accepts backend active turns that omit nullable optional fields", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      snapshot_version: "tutor_conversation_snapshot_v2",
      conversation: { conversation_id: "conversation-1", title: "测试", control_version: 2, control_state: "running", queue_paused: false, queue_pause_reason: null, pending_count: 0, max_pending: 10 },
      active_turn: { turn_id: "turn-1", conversation_id: "conversation-1", interaction_protocol_version: "thread_turn_v2", status: "in_progress", input_revision: 3, created_at: "2026-08-14T00:00:00Z", updated_at: "2026-08-14T00:00:01Z" },
      active_thinking: null,
      pending_requests: [], queue: [], timeline: [], next_cursor: null, has_more: false, stream_cursor: "opaque.cursor",
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    const snapshot = await fetchTutorConversationSnapshot({ userId: "user-1", conversationId: "conversation-1" });
    expect(snapshot.active_turn).toMatchObject({ input_revision: 3, retry_of_turn_id: null, retry_root_turn_id: null, completion_reason: null });
  });


  it("accepts exact active public thinking and rejects extra fields", async () => {
    const base = {
      snapshot_version: "tutor_conversation_snapshot_v2",
      conversation: { conversation_id: "conversation-1", title: "测试", control_version: 2, control_state: "running", queue_paused: false, queue_pause_reason: null, pending_count: 0, max_pending: 10 },
      active_turn: { turn_id: "turn-1", conversation_id: "conversation-1", interaction_protocol_version: "thread_turn_v2", status: "in_progress", input_revision: 3, retry_of_turn_id: null, retry_root_turn_id: null, completion_reason: null, created_at: "2026-08-14T00:00:00Z", updated_at: "2026-08-14T00:00:01Z" },
      active_thinking: { turn_id: "turn-1", input_revision: 3, generation: 10001, state: "active", text: "先确认目标。", complete: false, last_event_sequence: 8 },
      pending_requests: [], queue: [], timeline: [], next_cursor: null, has_more: false, stream_cursor: "opaque.cursor",
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(base), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...base, active_thinking: { ...base.active_thinking, reasoning: "protected" } }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchTutorConversationSnapshot({ userId: "user-1", conversationId: "conversation-1" })).resolves.toMatchObject({
      active_thinking: { text: "先确认目标。", generation: 10001 },
    });
    await expect(fetchTutorConversationSnapshot({ userId: "user-1", conversationId: "conversation-1" })).rejects.toThrow("Tutor snapshot API returned an invalid payload");
  });

  it("accepts Codex runtime process steps and rejects unknown step keys", async () => {
    const process = {
      kind: "process",
      id: "turn-1",
      turn_id: "turn-1",
      run_id: "turn-1",
      display_state: "completed",
      steps: [
        { key: "input_received", state: "completed", label: "已接收你的问题" },
        { key: "runtime_started", state: "completed", label: "已启动受控 Agent Runtime" },
        { key: "domain_tool_running", state: "completed", label: "正在执行受控学习工具" },
        { key: "domain_tool_completed", state: "completed", label: "已完成受控学习工具" },
        { key: "learning_reply_generated", state: "completed", label: "已完成一次受控学习建议生成" },
      ],
      elapsed_seconds: 11,
      created_at: "2026-08-19T10:57:14Z",
      finished_at: "2026-08-19T10:57:26Z",
    };
    const snapshot = {
      snapshot_version: "tutor_conversation_snapshot_v2",
      conversation: { conversation_id: "conversation-1", title: "测试", control_version: 2, control_state: "idle", queue_paused: false, queue_pause_reason: null, pending_count: 0, max_pending: 10 },
      active_turn: null,
      active_thinking: null,
      pending_requests: [], queue: [], timeline: [process], next_cursor: null, has_more: false, stream_cursor: "opaque.cursor",
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(snapshot), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        ...snapshot,
        timeline: [{ ...process, steps: [{ key: "provider_reasoning", state: "completed", label: "protected" }] }],
      }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchTutorConversationSnapshot({ userId: "user-1", conversationId: "conversation-1" })).resolves.toMatchObject({
      timeline: [{ kind: "process", steps: [
        { key: "input_received" },
        { key: "runtime_started" },
        { key: "domain_tool_running" },
        { key: "domain_tool_completed" },
        { key: "learning_reply_generated" },
      ] }],
    });
    await expect(fetchTutorConversationSnapshot({ userId: "user-1", conversationId: "conversation-1" })).rejects.toThrow("Tutor snapshot API returned an invalid payload");
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
