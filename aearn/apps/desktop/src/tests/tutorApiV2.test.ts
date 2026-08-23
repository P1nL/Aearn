import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchTutorConversationSnapshot, fetchTutorThreadTurnV2Capability, mutateTeachingSession, openTeachingSession } from "../api";

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

  it("accepts snapshot v3 raw Runtime output and rejects provider metadata", async () => {
    const runtimeOutput = {
      output_version: "tutor_runtime_output_v1",
      input_revision: 3,
      generation: 7,
      reasoning_items: [{ item_id: "reasoning-1", text: "先读取 confirmed facts。", state: "streaming", last_sequence: 8 }],
      final_answer_item: { item_id: "answer-1", text: "接下来只询问学习目标。", state: "streaming", last_sequence: 9 },
    };
    const base = {
      snapshot_version: "tutor_conversation_snapshot_v3",
      conversation: { conversation_id: "conversation-1", title: "测试", control_version: 2, control_state: "running", queue_paused: false, queue_pause_reason: null, pending_count: 0, max_pending: 10 },
      active_turn: { turn_id: "turn-1", conversation_id: "conversation-1", interaction_protocol_version: "thread_turn_v2", status: "in_progress", input_revision: 3, retry_of_turn_id: null, retry_root_turn_id: null, completion_reason: null, created_at: "2026-08-20T00:00:00Z", updated_at: "2026-08-20T00:00:01Z" },
      active_thinking: null,
      active_runtime_output: runtimeOutput,
      pending_requests: [], queue: [], timeline: [], next_cursor: null, has_more: false, stream_cursor: "opaque.cursor",
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(base), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        ...base,
        active_runtime_output: { ...runtimeOutput, model_provider: "private" },
      }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchTutorConversationSnapshot({ userId: "user-1", conversationId: "conversation-1" })).resolves.toMatchObject({
      snapshot_version: "tutor_conversation_snapshot_v3",
      active_runtime_output: {
        reasoning_items: [{ text: "先读取 confirmed facts。" }],
        final_answer_item: { text: "接下来只询问学习目标。" },
      },
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



  it("accepts exact teaching session groups and rejects protected or unknown projection fields", async () => {
    const group = {
      session_id: "11111111-1111-4111-8111-111111111111",
      track_id: "22222222-2222-4222-8222-222222222222",
      track_version: 3,
      conversation_id: "33333333-3333-4333-8333-333333333333",
      knowledge_key: "javascript.closure",
      status: "active",
      mode: "guided",
      session_version: 4,
      progress_version: 2,
      assignment_id: "44444444-4444-4444-8444-444444444444",
      assignment_version: 2,
      document_id: "55555555-5555-4555-8555-555555555555",
      checkpoint_id: "66666666-6666-4666-8666-666666666666",
      paused_at: null,
      completed_at: null,
      last_activity_at: "2026-08-23T05:00:00Z",
      action_shelf: null,
      allowed_actions: [],
      turn_ids: ["77777777-7777-4777-8777-777777777777"],
    };
    const base = {
      snapshot_version: "tutor_conversation_snapshot_v3",
      conversation: { conversation_id: group.conversation_id, title: "闭包", control_version: 2, control_state: "idle", queue_paused: false, queue_pause_reason: null, pending_count: 0, max_pending: 10 },
      active_turn: null,
      active_thinking: null,
      active_runtime_output: null,
      pending_requests: [], queue: [], timeline: [], next_cursor: null, has_more: false, stream_cursor: "opaque.cursor",
      teaching_sessions: [group],
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(base), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...base, teaching_sessions: [{ ...group, provider_body: { secret: true } }] }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...base, teaching_sessions: [group, { ...group, session_id: "88888888-8888-4888-8888-888888888888" }] }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchTutorConversationSnapshot({ userId: "user-1", conversationId: group.conversation_id })).resolves.toMatchObject({
      teaching_sessions: [{ session_id: group.session_id, turn_ids: group.turn_ids }],
    });
    await expect(fetchTutorConversationSnapshot({ userId: "user-1", conversationId: group.conversation_id })).rejects.toThrow("Tutor snapshot API returned an invalid payload");
    await expect(fetchTutorConversationSnapshot({ userId: "user-1", conversationId: group.conversation_id })).rejects.toThrow("Tutor snapshot API returned an invalid payload");
  });

  it("accepts exact teaching-session message references and rejects public message content", async () => {
    const reference = {
      reference_id: "88888888-8888-4888-8888-888888888888",
      schema_version: "tutor_context_reference_v1",
      kind: "teaching_session_message",
      learning_track_id: "22222222-2222-4222-8222-222222222222",
      knowledge_key: "javascript.scope",
      teaching_session_id: "11111111-1111-4111-8111-111111111111",
      message_id: "99999999-9999-4999-8999-999999999999",
      turn_id: "77777777-7777-4777-8777-777777777777",
      role: "tutor",
      message_summary: "历史讲解（exact session/message reference）",
      message_created_at: "2026-08-22T08:00:00Z",
      source_version: "teaching-session:2",
      source_hash: "a".repeat(64),
      safe_payload_hash: "b".repeat(64),
      created_at: "2026-08-23T08:00:00Z",
    };
    const base = {
      snapshot_version: "tutor_conversation_snapshot_v2",
      conversation: { conversation_id: "conversation-1", title: "测试", control_version: 2, control_state: "idle", queue_paused: false, queue_pause_reason: null, pending_count: 0, max_pending: 10 },
      active_turn: null, active_thinking: null, pending_requests: [], queue: [],
      timeline: [{ kind: "message", id: "message-current", turn_id: "turn-current", role: "learner", content: "继续解释。", public_thinking_text: "", public_thinking_steps: [], context_references: [reference], in_reply_to_item_id: null, created_at: "2026-08-23T08:00:00Z" }],
      next_cursor: null, has_more: false, stream_cursor: "opaque.cursor",
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(base), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...base, timeline: [{ ...base.timeline[0], context_references: [{ ...reference, message_content: "protected" }] }] }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchTutorConversationSnapshot({ userId: "user-1", conversationId: "conversation-1" })).resolves.toMatchObject({
      timeline: [{ context_references: [{ kind: "teaching_session_message", message_id: reference.message_id }] }],
    });
    await expect(fetchTutorConversationSnapshot({ userId: "user-1", conversationId: "conversation-1" })).rejects.toThrow("Tutor snapshot API returned an invalid payload");
  });

  it("sends exact expected versions for mode and Action Shelf mutations", async () => {
    const session = {
      session_id: "11111111-1111-4111-8111-111111111111", track_id: "22222222-2222-4222-8222-222222222222", track_version: 3,
      conversation_id: "33333333-3333-4333-8333-333333333333", knowledge_key: "javascript.closure", status: "active", mode: "guided",
      session_version: 1, progress_version: 2, assignment_id: "44444444-4444-4444-8444-444444444444", assignment_version: 2,
      document_id: "55555555-5555-4555-8555-555555555555", checkpoint_id: "66666666-6666-4666-8666-666666666666",
      paused_at: null, completed_at: null, last_activity_at: "2026-08-23T05:00:00Z",
      checkpoint: { checkpoint_id: "66666666-6666-4666-8666-666666666666", session_version: 1,
        objective: { objective_id: "knowledge:javascript.closure", summary: "闭包", source_handles: ["knowledge:javascript.closure"] },
        active_focus: { focus_id: "knowledge:javascript.closure", focus_kind: "knowledge", summary: "闭包", source_handles: ["knowledge:javascript.closure"] },
        suspended_focuses: [], unresolved_questions: [], covered_concepts: [], evidence_cursors: [], pause_reason: "soft_pause", recommended_action_key: "continue" },
      action_shelf: { schema_version: "teaching_action_shelf_v1", teaching_session_id: "11111111-1111-4111-8111-111111111111", session_version: 1,
        checkpoint_id: "66666666-6666-4666-8666-666666666666", state: "ready",
        primary_action: { key: "continue", label: "继续", emphasis: "primary", enabled: true, disabled_reason: null, target_kind: "teaching_control", target_id: null,
          expected_versions: { session: 1, track: 3, progress: 2, assignment: 2 } }, secondary_actions: [], overflow_actions: [] },
      allowed_actions: ["continue"],
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ teaching_session: session, created: false, pending_run: null, idempotent_replayed: false }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ teaching_session: { ...session, mode: "free_reading", session_version: 2, checkpoint: { ...session.checkpoint, session_version: 2 }, action_shelf: { ...session.action_shelf, session_version: 2, state: "free_reading", primary_action: null }, allowed_actions: [] }, pending_run: null, idempotent_replayed: false }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await openTeachingSession({ userId: "user-1", trackId: session.track_id, knowledgeKey: session.knowledge_key, conversationId: session.conversation_id,
      expectedTrackVersion: 3, expectedProgressVersion: 2, expectedAssignmentVersion: 2, mode: "guided", clientActionId: "open:test" });
    await mutateTeachingSession({ userId: "user-1", trackId: session.track_id, sessionId: session.session_id, controlKey: "switch_mode",
      expectedSessionVersion: 1, expectedTrackVersion: 3, expectedProgressVersion: 2, expectedAssignmentVersion: 2,
      targetMode: "free_reading", clientActionId: "switch:test" });

    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ user_id: "user-1", conversation_id: session.conversation_id,
      expected_track_version: 3, expected_progress_version: 2, expected_assignment_version: 2, mode: "guided", client_action_id: "open:test" });
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({ user_id: "user-1", control_key: "switch_mode",
      expected_session_version: 1, expected_track_version: 3, expected_progress_version: 2, expected_assignment_version: 2,
      target_mode: "free_reading", admit_run: false, client_action_id: "switch:test" });
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
