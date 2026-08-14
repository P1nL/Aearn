import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  fetchTutorThreadTurnV2Capability: vi.fn(), fetchTutorConversationSnapshot: vi.fn(), respondToTutorInteractionRequest: vi.fn(),
  acceptTutorConversationInput: vi.fn(), acceptTutorFirstTurn: vi.fn(), buildTutorConversationEventsUrl: vi.fn(() => "http://events.test"),
  correctTutorMemory: vi.fn(), deleteTutorMemory: vi.fn(), deleteTutorQueueItem: vi.fn(), dismissTutorInbox: vi.fn(), editTutorQueueItem: vi.fn(), executeTutorQueueItem: vi.fn(),
  fetchTutorActivity: vi.fn(), fetchTutorInbox: vi.fn(), fetchTutorMemory: vi.fn(), fetchTutorPlanRevisions: vi.fn(), fetchTutorPreferences: vi.fn(), interruptTutorTurn: vi.fn(),
  markTutorInboxRead: vi.fn(), reorderTutorQueue: vi.fn(), resumeTutorQueue: vi.fn(), retryTutorTurn: vi.fn(), rollbackTutorPlan: vi.fn(), steerTutorQueueItem: vi.fn(), updateTutorPreferences: vi.fn(),
}));
vi.mock("../../../api", () => api);
vi.mock("../../../hooks/useTutorConversationStream", () => ({ useTutorConversationStream: () => ({ status: "streaming", error: null, cursor: "opaque", retry: vi.fn(), close: vi.fn() }) }));

import { TutorConversationSurface } from "../TutorConversationSurface";

const prompt = "请说明你希望先学习事件循环的哪一部分？";
const snapshot = {
  snapshot_version: "tutor_conversation_snapshot_v1" as const,
  conversation: { conversation_id: "conversation-1", title: "测试", control_version: 4, control_state: "waiting" as const, queue_paused: true, queue_pause_reason: "pending_request" as const, pending_count: 1, max_pending: 10 },
  active_turn: null,
  pending_requests: [{ kind: "elicitation" as const, id: "item-1", request_id: "request-1", turn_id: "turn-1", request_kind: "clarification" as const, actor: "learner" as const, state: "pending" as const, version: 2, required: true as const, prompt, presentation: { type: "text" as const, field_key: null, minimum_length: 1, maximum_length: 200, multiline: true }, allowed_actions: ["respond" as const], answer_turn_id: null, created_at: "2026-08-14T00:00:00Z", resolved_at: null }],
  queue: [{ item_id: "queue-1", state: "pending" as const, position: 1, version: 1, content: "不应在请求席位出现", created_at: "2026-08-14T00:00:00Z", updated_at: "2026-08-14T00:00:00Z" }],
  timeline: [], next_cursor: null, has_more: false, stream_cursor: "opaque.cursor",
};

describe("TutorConversationSurface typed request seat", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.fetchTutorThreadTurnV2Capability.mockResolvedValue({ schema_version: "tutor_thread_turn_v2_capability_v1", cutover_version: "tutor_thread_turn_v2_global_v1", desktop_contract_version: "tutor_thread_turn_v2_desktop_v1", env_allowed: true, state: "enabled", generation: 1, summary_hash: "0".repeat(64), block_code: null, effective_enabled: true, counts: {}, prepared_at: null, enabled_at: null, updated_at: null });
    api.fetchTutorConversationSnapshot.mockResolvedValue(snapshot);
    api.respondToTutorInteractionRequest.mockResolvedValue({});
    api.executeTutorQueueItem.mockResolvedValue({});
  });

  it("fully replaces ordinary composer and Queue controls, then sends exact request version", async () => {
    const user = userEvent.setup();
    render(<TutorConversationSurface user={{ id: "user-1", display_name: "测试用户", learning_style: null, teaching_preference: null, encouragement_preference: null, profession: null, background_context: null, preferred_time_slots: [], reminder_preference: {}, created_at: "2026-08-14T00:00:00Z", updated_at: "2026-08-14T00:00:00Z" }} enabled isActive selectedConversationId="conversation-1" onSelectConversation={vi.fn()} showControls={false} />);
    const answer = await screen.findByRole("textbox", { name: prompt });
    expect(screen.queryByRole("region", { name: "待处理 Queue" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "继续当前对话" })).not.toBeInTheDocument();
    await user.type(answer, "先学习任务队列");
    await user.click(screen.getByRole("button", { name: "提交响应" }));
    await waitFor(() => expect(api.respondToTutorInteractionRequest).toHaveBeenCalledWith(expect.objectContaining({ itemId: "item-1", expectedRequestVersion: 2, response: { kind: "clarification", answer_text: "先学习任务队列" } })));
  });


  it("keeps immediate execute available during an active turn and sends snapshot CAS", async () => {
    const user = userEvent.setup();
    api.fetchTutorConversationSnapshot.mockResolvedValue({
      ...snapshot,
      conversation: { ...snapshot.conversation, control_state: "running", queue_paused: false, queue_pause_reason: null },
      active_turn: { turn_id: "turn-active", conversation_id: "conversation-1", interaction_protocol_version: "thread_turn_v2", status: "in_progress", input_revision: 5, retry_of_turn_id: null, retry_root_turn_id: null, completion_reason: null, created_at: "2026-08-14T00:00:00Z", updated_at: "2026-08-14T00:00:01Z" },
      pending_requests: [],
    });
    render(<TutorConversationSurface user={{ id: "user-1", display_name: "测试用户", learning_style: null, teaching_preference: null, encouragement_preference: null, profession: null, background_context: null, preferred_time_slots: [], reminder_preference: {}, created_at: "2026-08-14T00:00:00Z", updated_at: "2026-08-14T00:00:00Z" }} enabled isActive selectedConversationId="conversation-1" onSelectConversation={vi.fn()} showControls={false} />);
    const execute = await screen.findByRole("button", { name: "中断并执行" });
    expect(execute).toBeEnabled();
    expect(screen.getByText(/Steer 会影响当前处理/)).toBeInTheDocument();
    await user.click(execute);
    await waitFor(() => expect(api.executeTutorQueueItem).toHaveBeenCalledWith(expect.objectContaining({
      conversationId: "conversation-1", itemId: "queue-1", expectedControlVersion: 4,
    })));
  });
});
