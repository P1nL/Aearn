import { act, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  fetchTutorThreadTurnV2Capability: vi.fn(), fetchTutorArtifact: vi.fn(), fetchTutorArtifactAttempt: vi.fn(), fetchTutorConversationSnapshot: vi.fn(), respondToTutorInteractionRequest: vi.fn(), actOnTutorArtifact: vi.fn(),
  acceptTutorConversationInput: vi.fn(), acceptTutorFirstTurn: vi.fn(), buildTutorConversationEventsUrl: vi.fn(() => "http://events.test"),
  correctTutorMemory: vi.fn(), deleteTutorMemory: vi.fn(), deleteTutorQueueItem: vi.fn(), dismissTutorInbox: vi.fn(), editTutorQueueItem: vi.fn(), executeTutorQueueItem: vi.fn(),
  fetchTutorActivity: vi.fn(), fetchTutorInbox: vi.fn(), fetchTutorMemory: vi.fn(), fetchTutorPlanRevisions: vi.fn(), fetchTutorPreferences: vi.fn(), interruptTutorTurn: vi.fn(),
  markTutorInboxRead: vi.fn(), reorderTutorQueue: vi.fn(), resumeTutorQueue: vi.fn(), retryTutorTurn: vi.fn(), rollbackTutorPlan: vi.fn(), steerTutorQueueItem: vi.fn(), updateTutorPreferences: vi.fn(),
}));
const streamHarness = vi.hoisted(() => ({
  options: null as { onEvent?: (event: unknown) => void } | null,
}));
vi.mock("../../../api", () => api);
vi.mock("../../../hooks/useTutorConversationStream", () => ({
  useTutorConversationStream: (_url: string | null, options: { onEvent?: (event: unknown) => void }) => {
    streamHarness.options = options;
    return { status: "streaming", error: null, cursor: "opaque", retry: vi.fn(), close: vi.fn() };
  },
}));
vi.mock("@monaco-editor/react", () => ({
  default: (props: { value: string; options: { ariaLabel: string; readOnly: boolean }; onChange?: (value: string) => void }) =>
    <textarea aria-label={props.options.ariaLabel} readOnly={props.options.readOnly} value={props.value} onChange={(event) => props.onChange?.(event.currentTarget.value)} />,
}));

import { resetArtifactUiStateCachesForTests, resetCodeArtifactDraftsForTests } from "../artifacts";
import { TutorConversationSurface } from "../TutorConversationSurface";

const prompt = "请说明你希望先学习事件循环的哪一部分？";
const userProfile = {
  id: "user-1", display_name: "测试用户", learning_style: null, teaching_preference: null,
  encouragement_preference: null, profession: null, background_context: null,
  preferred_time_slots: [], reminder_preference: {}, created_at: "2026-08-14T00:00:00Z", updated_at: "2026-08-14T00:00:00Z",
};
const snapshot = {
  snapshot_version: "tutor_conversation_snapshot_v2" as const,
  conversation: { conversation_id: "conversation-1", title: "测试", control_version: 4, control_state: "waiting" as const, queue_paused: true, queue_pause_reason: "pending_request" as const, pending_count: 1, max_pending: 10 },
  active_turn: null,
  active_thinking: null,
  pending_requests: [{ kind: "elicitation" as const, id: "item-1", request_id: "request-1", turn_id: "turn-1", request_kind: "clarification" as const, actor: "learner" as const, state: "pending" as const, version: 2, required: true as const, prompt, public_thinking_text: "", presentation: { type: "text" as const, field_key: null, minimum_length: 1, maximum_length: 200, multiline: true }, allowed_actions: ["respond" as const], answer_turn_id: null, created_at: "2026-08-14T00:00:00Z", resolved_at: null }],
  queue: [{ item_id: "queue-1", state: "pending" as const, position: 1, version: 1, content: "不应在请求席位出现", created_at: "2026-08-14T00:00:00Z", updated_at: "2026-08-14T00:00:00Z" }],
  timeline: [], next_cursor: null, has_more: false, stream_cursor: "opaque.cursor",
};

function renderSurface(options: Partial<ComponentProps<typeof TutorConversationSurface>> = {}) {
  return render(<TutorConversationSurface user={userProfile} enabled isActive selectedConversationId="conversation-1" onSelectConversation={vi.fn()} showControls={false} {...options} />);
}

function emitStreamEvent(event: unknown) {
  act(() => streamHarness.options?.onEvent?.(event));
}


describe("Harness terminal error projection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    streamHarness.options = null;
    window.sessionStorage.clear();
    resetArtifactUiStateCachesForTests();
    resetCodeArtifactDraftsForTests();
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    api.fetchTutorThreadTurnV2Capability.mockResolvedValue({ schema_version: "tutor_thread_turn_v2_capability_v1", cutover_version: "tutor_thread_turn_v2_global_v1", desktop_contract_version: "tutor_thread_turn_v2_desktop_v1", env_allowed: true, state: "enabled", generation: 1, summary_hash: "0".repeat(64), block_code: null, effective_enabled: true, counts: {}, prepared_at: null, enabled_at: null, updated_at: null });
    api.fetchTutorConversationSnapshot.mockResolvedValue(snapshot);
    api.respondToTutorInteractionRequest.mockResolvedValue({});
    api.executeTutorQueueItem.mockResolvedValue({});
  });
  afterEach(() => vi.unstubAllGlobals());

  it.each([false, true])("renders only the server error and retry authority (%s) after repeated terminal refresh and reload", async (recoverable) => {
    const error = { kind: "error", id: "stable-terminal-error", turn_id: "turn-1", code: "CAPABILITY_DENIED",
      message: recoverable ? "Tutor 未能安全完成本轮处理。你可以重试本轮。" : "Tutor 未能安全完成本轮处理。请调整问题后发送一条新消息。",
      recoverable, created_at: "2026-09-08T00:00:00Z" };
    const terminal = { ...snapshot, pending_requests: [], queue: [],
      conversation: { ...snapshot.conversation, control_state: "idle", queue_paused: false, queue_pause_reason: null, pending_count: 0 },
      timeline: [{ kind: "process", id: "turn-1", turn_id: "turn-1", run_id: "turn-1", display_state: "unavailable",
        steps: [], elapsed_seconds: 1, created_at: error.created_at, finished_at: error.created_at }, error] };
    api.fetchTutorConversationSnapshot.mockResolvedValue(terminal);
    const view = renderSurface();
    expect(await screen.findByText(error.message)).toBeInTheDocument();
    expect(screen.queryAllByRole("button", { name: "重试本轮" })).toHaveLength(recoverable ? 1 : 0);
    for (let sequence = 1; sequence <= 2; sequence += 1) {
      emitStreamEvent({ event_id: "terminal-event", sequence, kind: "turn_updated", turn_id: "turn-1", payload: {}, occurred_at: error.created_at });
      await waitFor(() => expect(api.fetchTutorConversationSnapshot.mock.calls.length).toBeGreaterThan(sequence));
      expect(screen.getAllByText(error.message)).toHaveLength(1);
    }
    view.unmount();
    renderSurface();
    expect(await screen.findByText(error.message)).toBeInTheDocument();
    expect(screen.getAllByText(error.message)).toHaveLength(1);
    expect(screen.queryByText("unavailable")).not.toBeInTheDocument();
    if (recoverable) {
      api.retryTutorTurn.mockResolvedValue({});
      await userEvent.click(screen.getByRole("button", { name: "重试本轮" }));
      expect(api.retryTutorTurn).toHaveBeenCalledWith(expect.objectContaining({ turnId: "turn-1", expectedControlVersion: 4 }));
    } else {
      expect(api.retryTutorTurn).not.toHaveBeenCalled();
    }
  });
});
