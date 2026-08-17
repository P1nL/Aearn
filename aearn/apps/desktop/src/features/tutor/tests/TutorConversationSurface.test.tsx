import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  fetchTutorThreadTurnV2Capability: vi.fn(), fetchTutorConversationSnapshot: vi.fn(), respondToTutorInteractionRequest: vi.fn(),
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

import { TutorConversationSurface } from "../TutorConversationSurface";

const prompt = "请说明你希望先学习事件循环的哪一部分？";
const userProfile = {
  id: "user-1", display_name: "测试用户", learning_style: null, teaching_preference: null,
  encouragement_preference: null, profession: null, background_context: null,
  preferred_time_slots: [], reminder_preference: {}, created_at: "2026-08-14T00:00:00Z", updated_at: "2026-08-14T00:00:00Z",
};
const activeTurn = {
  turn_id: "turn-active", conversation_id: "conversation-1", interaction_protocol_version: "thread_turn_v2" as const,
  status: "in_progress" as const, input_revision: 5, retry_of_turn_id: null, retry_root_turn_id: null,
  completion_reason: null, created_at: "2026-08-14T00:00:00Z", updated_at: "2026-08-14T00:00:01Z",
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

function renderSurface(options: { mode?: "general" | "plan_drafting"; planningComposerPlaceholder?: string } = {}) {
  return render(<TutorConversationSurface user={userProfile} enabled isActive selectedConversationId="conversation-1" onSelectConversation={vi.fn()} showControls={false} {...options} />);
}

function emitStreamEvent(event: unknown) {
  act(() => streamHarness.options?.onEvent?.(event));
}

describe("TutorConversationSurface typed request seat", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    streamHarness.options = null;
    api.fetchTutorThreadTurnV2Capability.mockResolvedValue({ schema_version: "tutor_thread_turn_v2_capability_v1", cutover_version: "tutor_thread_turn_v2_global_v1", desktop_contract_version: "tutor_thread_turn_v2_desktop_v1", env_allowed: true, state: "enabled", generation: 1, summary_hash: "0".repeat(64), block_code: null, effective_enabled: true, counts: {}, prepared_at: null, enabled_at: null, updated_at: null });
    api.fetchTutorConversationSnapshot.mockResolvedValue(snapshot);
    api.respondToTutorInteractionRequest.mockResolvedValue({});
    api.executeTutorQueueItem.mockResolvedValue({});
  });

  it("keeps the planning Composer available with the caller-owned draft revision prompt", async () => {
    api.fetchTutorConversationSnapshot.mockResolvedValue({
      ...snapshot,
      conversation: { ...snapshot.conversation, control_state: "idle", pending_count: 0, queue_paused: false, queue_pause_reason: null },
      pending_requests: [],
      queue: [],
    });

    renderSurface({ mode: "plan_drafting", planningComposerPlaceholder: "对计划有修改意见？直接告诉我……" });

    expect(await screen.findByPlaceholderText("对计划有修改意见？直接告诉我……")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "批准" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "拒绝" })).not.toBeInTheDocument();
  });

  it("renders a formal Tutor question once when the same Turn also contains its typed request record", async () => {
    const requestItem = {
      ...snapshot.pending_requests[0],
      public_thinking_text: "先确认网站目标，再收窄学习路径。",
    };
    const formalMessage = {
      kind: "message" as const,
      id: "message-question",
      turn_id: requestItem.turn_id,
      role: "tutor" as const,
      content: prompt,
      public_thinking_text: requestItem.public_thinking_text,
      public_thinking_steps: [],
      context_references: [],
      in_reply_to_item_id: null,
      created_at: "2026-08-14T00:00:01Z",
    };
    api.fetchTutorConversationSnapshot.mockResolvedValue({
      ...snapshot,
      pending_requests: [requestItem],
      timeline: [requestItem, formalMessage],
    });

    renderSurface();

    await screen.findByRole("textbox", { name: prompt });
    expect(document.querySelectorAll(".tutor-request-history")).toHaveLength(0);
    expect(screen.queryByText("Tutor 请求")).not.toBeInTheDocument();
    expect(screen.getAllByText(prompt)).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "Think" })).toHaveLength(1);
  });

  it("fully replaces ordinary composer and Queue controls, then sends exact request version", async () => {
    const user = userEvent.setup();
    renderSurface();
    const answer = await screen.findByRole("textbox", { name: prompt });
    expect(screen.queryByRole("region", { name: "待处理 Queue" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "继续当前对话" })).not.toBeInTheDocument();
    expect(screen.queryByText("需要你的输入")).not.toBeInTheDocument();
    expect(screen.queryByText(/类型化请求完全占用 composer 席位/)).not.toBeInTheDocument();
    await user.type(answer, "先学习任务队列");
    await user.click(screen.getByRole("button", { name: "提交响应" }));
    await waitFor(() => expect(api.respondToTutorInteractionRequest).toHaveBeenCalledWith(expect.objectContaining({ itemId: "item-1", expectedRequestVersion: 2, response: { kind: "clarification", answer_text: "先学习任务队列" } })));
  });

  it("renders a clean single-select seat and omits request-history helper copy", async () => {
    const user = userEvent.setup();
    const selectRequest = {
      ...snapshot.pending_requests[0],
      presentation: {
        type: "single_select" as const,
        field_key: "experience_level",
        options: [
          { value: "none", label: "完全没有经验" },
          { value: "basic", label: "了解基础" },
        ],
        recommended: null,
      },
    };
    api.fetchTutorConversationSnapshot.mockResolvedValue({
      ...snapshot,
      pending_requests: [selectRequest],
      timeline: [selectRequest],
    });

    renderSurface();

    const none = await screen.findByRole("radio", { name: "完全没有经验" });
    expect(document.querySelectorAll(".tutor-request-history")).toHaveLength(1);
    const basic = screen.getByRole("radio", { name: "了解基础" });
    const submit = screen.getByRole("button", { name: "提交响应" });
    expect(screen.queryByRole("combobox", { name: prompt })).not.toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(2);
    expect(screen.queryByText("请选择")).not.toBeInTheDocument();
    expect(screen.queryByText("需要你的输入")).not.toBeInTheDocument();
    expect(screen.queryByText(/类型化请求完全占用 composer 席位/)).not.toBeInTheDocument();
    expect(screen.queryByText("请在下方类型化请求席位中响应")).not.toBeInTheDocument();
    expect(none).not.toBeChecked();
    expect(submit).toBeDisabled();
    await user.click(basic);
    expect(basic).toBeChecked();
    expect(submit).toBeEnabled();
  });

  it("mounts the fresh answer-turn Think immediately after a typed request response", async () => {
    const user = userEvent.setup();
    const requestItem = {
      ...snapshot.pending_requests[0],
      prompt: "你的作品集网站想用哪种方式来做？",
      public_thinking_text: "先确认你偏好的实现方式。",
      presentation: {
        type: "single_select" as const,
        field_key: "experience_level",
        options: [{ value: "beginner", label: "HTML/CSS Interaction Beginner" }],
        recommended: null,
      },
    };
    const answerTurn = { ...activeTurn, turn_id: "turn-answer", input_revision: 1 };
    const activeAnswerSnapshot = {
      ...snapshot,
      conversation: { ...snapshot.conversation, control_state: "running" as const, pending_count: 0, queue_paused: false, queue_pause_reason: null },
      active_turn: answerTurn,
      active_thinking: null,
      pending_requests: [],
      queue: [],
      timeline: [{ ...requestItem, state: "answered" as const, version: 3, answer_turn_id: "turn-answer", resolved_at: "2026-08-15T00:00:03Z" }],
    };
    let resolveRefresh!: (value: typeof activeAnswerSnapshot) => void;
    api.fetchTutorConversationSnapshot
      .mockResolvedValueOnce({ ...snapshot, pending_requests: [requestItem], timeline: [requestItem] })
      .mockImplementationOnce(() => new Promise((resolve) => { resolveRefresh = resolve; }));
    api.respondToTutorInteractionRequest.mockResolvedValue({
      conversation_id: "conversation-1", run_id: "turn-answer", input_revision: 1, message_id: "message-answer",
      event_cursor: 8, dispatch_job_id: "job-answer", merged: false, input_replayed: false, idempotent_replayed: false,
      run: {
        run_id: "turn-answer", conversation_id: "conversation-1", origin: "interactive", status: "queued", input_revision: 1,
        cancelled: false, iteration_count: 0, model_call_count: 0, capability_call_count: 0, effect_count: 0, terminal_outcome: null,
        continuation_kind: null, interaction_protocol_version: "thread_turn_v2", retry_of_turn_id: null, retry_root_turn_id: null,
        response_to_request_id: "request-1", completion_reason: null, created_at: "2026-08-15T00:00:03Z", updated_at: "2026-08-15T00:00:03Z",
      },
      process: null, replaced_run_id: null, replaced_process: null, context_references: [],
      request: { ...requestItem, state: "answered", version: 3, answer_turn_id: "turn-answer", resolved_at: "2026-08-15T00:00:03Z", allowed_actions: [] },
      response_replayed: false,
    });

    renderSurface();
    await user.click(await screen.findByRole("radio", { name: "HTML/CSS Interaction Beginner" }));
    await user.click(screen.getByRole("button", { name: "提交响应" }));

    const freshThink = await screen.findByRole("status", { name: "Think" });
    expect(freshThink.closest("article")).toHaveAttribute("data-turn-id", "turn-answer");
    expect(screen.queryByRole("button", { name: "提交响应" })).not.toBeInTheDocument();
    expect(api.fetchTutorConversationSnapshot).toHaveBeenCalledTimes(2);

    emitStreamEvent({
      cursor: "cursor-answer-1", event_id: "event-answer-1", sequence: 9, kind: "turn_output", turn_id: "turn-answer",
      item_id: null, item_kind: null, occurred_at: "2026-08-15T00:00:04Z", request_id: null,
      payload: { output_version: "tutor_public_thinking_stream_v1", input_revision: 1, generation: 20001, operation: "append", chunk_sequence: 1, text: "继续整理技术方案。" },
    });
    emitStreamEvent({
      cursor: "cursor-answer-2", event_id: "event-answer-2", sequence: 10, kind: "turn_output", turn_id: "turn-answer",
      item_id: null, item_kind: null, occurred_at: "2026-08-15T00:00:05Z", request_id: null,
      payload: { output_version: "tutor_public_thinking_stream_v1", input_revision: 1, generation: 20001, operation: "complete", chunk_sequence: 2 },
    });
    await waitFor(() => expect(document.querySelector('[data-turn-id="turn-answer"] button[aria-expanded="true"]')).not.toBeNull());
    await waitFor(() => expect(document.querySelector(".tutor-running-placeholder .tutor-thinking-text")?.textContent).toBe("继续整理技术方案。"));

    await act(async () => { resolveRefresh(activeAnswerSnapshot); });
    expect(document.querySelector('[data-turn-id="turn-answer"] button[aria-expanded="true"]')).not.toBeNull();
  });

  it("keeps the planning surface height hook on the DSH root", async () => {
    api.fetchTutorConversationSnapshot.mockResolvedValue({
      ...snapshot,
      conversation: { ...snapshot.conversation, pending_count: 0, queue_paused: false, queue_pause_reason: null },
      pending_requests: [],
      queue: [],
    });

    render(<TutorConversationSurface user={userProfile} enabled isActive selectedConversationId="conversation-1" onSelectConversation={vi.fn()} mode="plan_drafting" showControls={false} />);

    await screen.findByRole("textbox", { name: "告诉 Tutor 你的目标或调整意见" });
    const workspace = screen.getByRole("main", { name: "学习计划对话" });
    expect(workspace).toHaveClass("tutor-conversation-idle");
    expect(workspace.parentElement).toHaveClass("aearn-dsh-derived", "tutor-surface-root");
  });

  it("shows only a static Think row before public text arrives", async () => {
    const user = userEvent.setup();
    api.fetchTutorConversationSnapshot.mockResolvedValue({
      ...snapshot,
      conversation: { ...snapshot.conversation, control_state: "running", queue_paused: false, queue_pause_reason: null },
      active_turn: activeTurn,
      pending_requests: [],
    });
    renderSurface();
    const execute = await screen.findByRole("button", { name: "中断并执行" });
    const think = screen.getByRole("status", { name: "Think" });
    expect(think).toHaveTextContent("Think");
    expect(think.closest("article")).toHaveAttribute("data-turn-id", "turn-active");
    expect(screen.queryByRole("button", { name: "Think" })).not.toBeInTheDocument();
    expect(screen.queryByText("Tutor 正在思考")).not.toBeInTheDocument();
    expect(screen.queryByText(/完成后会显示/)).not.toBeInTheDocument();
    expect(execute).toBeEnabled();
    await user.click(execute);
    await waitFor(() => expect(api.executeTutorQueueItem).toHaveBeenCalledWith(expect.objectContaining({
      conversationId: "conversation-1", itemId: "queue-1", expectedControlVersion: 4,
    })));
  });

  it("reveals streamed Think only after the generation is validated and stable", async () => {
    api.fetchTutorConversationSnapshot.mockResolvedValue({
      ...snapshot,
      conversation: { ...snapshot.conversation, control_state: "running", pending_count: 0, queue_paused: false, queue_pause_reason: null },
      active_turn: activeTurn,
      pending_requests: [],
      queue: [],
    });
    renderSurface();
    await screen.findByRole("status", { name: "Think" });

    emitStreamEvent({
      cursor: "cursor-2", event_id: "event-2", sequence: 2, kind: "turn_output", turn_id: "turn-active",
      item_id: null, item_kind: null, occurred_at: "2026-08-14T00:00:02Z", request_id: null,
      payload: { output_version: "tutor_public_thinking_stream_v1", input_revision: 5, generation: 10001, operation: "append", chunk_sequence: 1, text: "先确认目标。\n再缩小范围。" },
    });

    expect(screen.getByRole("status", { name: "Think" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Think" })).not.toBeInTheDocument();
    expect(screen.queryByText("先确认目标。\n再缩小范围。")).not.toBeInTheDocument();

    await act(async () => { await new Promise((resolve) => window.setTimeout(resolve, 400)); });
    expect(screen.queryByRole("button", { name: "Think" })).not.toBeInTheDocument();
    expect(screen.queryByText("先确认目标。\n再缩小范围。")).not.toBeInTheDocument();

    emitStreamEvent({
      cursor: "cursor-3", event_id: "event-3", sequence: 3, kind: "turn_output", turn_id: "turn-active",
      item_id: null, item_kind: null, occurred_at: "2026-08-15T00:00:03Z", request_id: null,
      payload: { output_version: "tutor_public_thinking_stream_v1", input_revision: 5, generation: 10001, operation: "complete", chunk_sequence: 2 },
    });

    const disclosure = await screen.findByRole("button", { name: "Think" }, { timeout: 1_500 });
    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    await waitFor(() => expect(document.querySelector(".tutor-thinking-text")).toHaveTextContent("先确认目标。 再缩小范围。"));
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("keeps an unvalidated chunk out of the DOM even when discard arrives after the stability window", async () => {
    api.fetchTutorConversationSnapshot.mockResolvedValue({
      ...snapshot,
      conversation: { ...snapshot.conversation, control_state: "running", pending_count: 0, queue_paused: false, queue_pause_reason: null },
      active_turn: activeTurn,
      pending_requests: [],
      queue: [],
    });
    renderSurface();
    await screen.findByRole("status", { name: "Think" });

    emitStreamEvent({
      cursor: "cursor-buffer-1", event_id: "event-buffer-1", sequence: 2, kind: "turn_output", turn_id: "turn-active",
      item_id: null, item_kind: null, occurred_at: "2026-08-15T00:00:02Z", request_id: null,
      payload: { output_version: "tutor_public_thinking_stream_v1", input_revision: 5, generation: 10001, operation: "append", chunk_sequence: 1, text: "这段内容不应闪现。" },
    });
    expect(screen.queryByText("这段内容不应闪现。")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Think" })).not.toBeInTheDocument();

    await act(async () => { await new Promise((resolve) => window.setTimeout(resolve, 400)); });
    expect(screen.queryByText("这段内容不应闪现。")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Think" })).not.toBeInTheDocument();

    emitStreamEvent({
      cursor: "cursor-buffer-2", event_id: "event-buffer-2", sequence: 3, kind: "turn_output", turn_id: "turn-active",
      item_id: null, item_kind: null, occurred_at: "2026-08-15T00:00:03Z", request_id: null,
      payload: { output_version: "tutor_public_thinking_stream_v1", input_revision: 5, generation: 10001, operation: "discard", chunk_sequence: 2 },
    });

    expect(screen.queryByText("这段内容不应闪现。")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Think" })).not.toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Think" })).toBeInTheDocument();
  });

  it("preserves displayed thinking until a recovery snapshot authoritatively clears it", async () => {
    const activeSnapshot = {
      ...snapshot,
      conversation: { ...snapshot.conversation, control_state: "running" as const, pending_count: 0, queue_paused: false, queue_pause_reason: null },
      active_turn: activeTurn,
      active_thinking: null,
      pending_requests: [],
      queue: [],
    };
    let resolveRecovery!: (value: typeof activeSnapshot) => void;
    api.fetchTutorConversationSnapshot
      .mockResolvedValueOnce(activeSnapshot)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveRecovery = resolve; }));
    renderSurface();
    await screen.findByRole("status", { name: "Think" });

    emitStreamEvent({
      cursor: "cursor-recovery-1", event_id: "event-recovery-1", sequence: 2, kind: "turn_output", turn_id: "turn-active",
      item_id: null, item_kind: null, occurred_at: "2026-08-15T00:00:02Z", request_id: null,
      payload: { output_version: "tutor_public_thinking_stream_v1", input_revision: 5, generation: 10001, operation: "append", chunk_sequence: 1, text: "恢复前保持显示。" },
    });
    emitStreamEvent({
      cursor: "cursor-recovery-2", event_id: "event-recovery-2", sequence: 3, kind: "turn_output", turn_id: "turn-active",
      item_id: null, item_kind: null, occurred_at: "2026-08-15T00:00:03Z", request_id: null,
      payload: { output_version: "tutor_public_thinking_stream_v1", input_revision: 5, generation: 10001, operation: "complete", chunk_sequence: 2 },
    });
    expect(await screen.findByText("恢复前保持显示。", {}, { timeout: 1_500 })).toBeInTheDocument();

    emitStreamEvent({
      cursor: "cursor-recovery-4", event_id: "event-recovery-4", sequence: 4, kind: "turn_output", turn_id: "turn-active",
      item_id: null, item_kind: null, occurred_at: "2026-08-15T00:00:04Z", request_id: null,
      payload: { output_version: "tutor_public_thinking_stream_v1", input_revision: 5, generation: 10001, operation: "append", chunk_sequence: 4, text: "不应直接追加。" },
    });
    await waitFor(() => expect(api.fetchTutorConversationSnapshot).toHaveBeenCalledTimes(2));
    expect(screen.getByText("恢复前保持显示。")).toBeInTheDocument();

    await act(async () => { resolveRecovery(activeSnapshot); });
    await waitFor(() => expect(screen.queryByText("恢复前保持显示。")).not.toBeInTheDocument());
    expect(screen.getByRole("status", { name: "Think" })).toBeInTheDocument();
  });

  it("resets and discards stale public-thinking generations without mixing text", async () => {
    api.fetchTutorConversationSnapshot.mockResolvedValue({
      ...snapshot,
      conversation: { ...snapshot.conversation, control_state: "running", pending_count: 0, queue_paused: false, queue_pause_reason: null },
      active_turn: activeTurn,
      pending_requests: [],
      queue: [],
    });
    renderSurface();
    await screen.findByRole("status", { name: "Think" });

    emitStreamEvent({
      cursor: "cursor-2", event_id: "event-2", sequence: 2, kind: "turn_output", turn_id: "turn-active",
      item_id: null, item_kind: null, occurred_at: "2026-08-15T00:00:02Z", request_id: null,
      payload: { output_version: "tutor_public_thinking_stream_v1", input_revision: 5, generation: 10001, operation: "append", chunk_sequence: 1, text: "旧尝试。" },
    });
    await act(async () => { await new Promise((resolve) => window.setTimeout(resolve, 400)); });
    expect(screen.queryByText("旧尝试。")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Think" })).not.toBeInTheDocument();

    emitStreamEvent({
      cursor: "cursor-3", event_id: "event-3", sequence: 3, kind: "turn_output", turn_id: "turn-active",
      item_id: null, item_kind: null, occurred_at: "2026-08-15T00:00:03Z", request_id: null,
      payload: { output_version: "tutor_public_thinking_stream_v1", input_revision: 5, generation: 10002, operation: "reset", chunk_sequence: 0 },
    });
    await waitFor(() => expect(screen.queryByText("旧尝试。")).not.toBeInTheDocument());
    expect(screen.getByRole("status", { name: "Think" })).toBeInTheDocument();

    emitStreamEvent({
      cursor: "cursor-4", event_id: "event-4", sequence: 4, kind: "turn_output", turn_id: "turn-active",
      item_id: null, item_kind: null, occurred_at: "2026-08-15T00:00:04Z", request_id: null,
      payload: { output_version: "tutor_public_thinking_stream_v1", input_revision: 5, generation: 10002, operation: "append", chunk_sequence: 1, text: "新尝试。" },
    });
    emitStreamEvent({
      cursor: "cursor-5", event_id: "event-5", sequence: 5, kind: "turn_output", turn_id: "turn-active",
      item_id: null, item_kind: null, occurred_at: "2026-08-15T00:00:05Z", request_id: null,
      payload: { output_version: "tutor_public_thinking_stream_v1", input_revision: 5, generation: 10002, operation: "complete", chunk_sequence: 2 },
    });
    await waitFor(() => expect(screen.getByText("新尝试。")).toBeInTheDocument());

    emitStreamEvent({
      cursor: "cursor-6", event_id: "event-6", sequence: 6, kind: "turn_output", turn_id: "turn-active",
      item_id: null, item_kind: null, occurred_at: "2026-08-15T00:00:06Z", request_id: null,
      payload: { output_version: "tutor_public_thinking_stream_v1", input_revision: 5, generation: 10002, operation: "discard", chunk_sequence: 3 },
    });
    await waitFor(() => expect(screen.queryByText("新尝试。")).not.toBeInTheDocument());
    expect(screen.getByRole("status", { name: "Think" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Think" })).not.toBeInTheDocument();
  });

  it("keeps incomplete snapshot thinking buffered until a validated complete event arrives", async () => {
    api.fetchTutorConversationSnapshot.mockResolvedValue({
      ...snapshot,
      conversation: { ...snapshot.conversation, control_state: "running", pending_count: 0, queue_paused: false, queue_pause_reason: null },
      active_turn: activeTurn,
      active_thinking: { turn_id: "turn-active", input_revision: 5, generation: 10001, state: "streaming", text: "快照中的候选文本。", complete: false, last_event_sequence: 7 },
      pending_requests: [],
      queue: [],
    });
    renderSurface();
    await screen.findByRole("status", { name: "Think" });

    await act(async () => { await new Promise((resolve) => window.setTimeout(resolve, 400)); });
    expect(screen.queryByText("快照中的候选文本。")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Think" })).not.toBeInTheDocument();

    emitStreamEvent({
      cursor: "cursor-snapshot-complete", event_id: "event-snapshot-complete", sequence: 8, kind: "turn_output", turn_id: "turn-active",
      item_id: null, item_kind: null, occurred_at: "2026-08-15T00:00:08Z", request_id: null,
      payload: { output_version: "tutor_public_thinking_stream_v1", input_revision: 5, generation: 10001, operation: "complete", chunk_sequence: 3 },
    });

    expect(await screen.findByText("快照中的候选文本。", {}, { timeout: 1_500 })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Think" })).toHaveAttribute("aria-expanded", "true");
  });

  it("keeps streamed thinking visible through snapshot handoff, then collapses only after every character is revealed", async () => {
    const user = userEvent.setup();
    const finalThinking = "先确认目标，再明确最小页面范围。";
    const finalAnswer = "我们先确定网站目标。";
    const liveSnapshot = {
      ...snapshot,
      conversation: { ...snapshot.conversation, control_state: "running" as const, pending_count: 0, queue_paused: false, queue_pause_reason: null },
      active_turn: activeTurn,
      active_thinking: { turn_id: "turn-active", input_revision: 5, generation: 10001, state: "complete" as const, text: "先确认目标，", complete: true, last_event_sequence: 7 },
      pending_requests: [],
      queue: [],
    };
    const handoffSnapshot = {
      ...snapshot,
      conversation: { ...snapshot.conversation, control_state: "idle" as const, pending_count: 0, queue_paused: false, queue_pause_reason: null },
      active_turn: null,
      active_thinking: null,
      pending_requests: [],
      queue: [],
      timeline: [],
    };
    const completedSnapshot = {
      ...handoffSnapshot,
      timeline: [{
        kind: "message" as const, id: "message-tutor", turn_id: "turn-active", role: "tutor" as const,
        content: finalAnswer, public_thinking_text: finalThinking, public_thinking_steps: [],
        context_references: [], in_reply_to_item_id: null, created_at: "2026-08-14T00:00:02Z",
      }],
    };
    api.fetchTutorConversationSnapshot
      .mockResolvedValueOnce(liveSnapshot)
      .mockResolvedValueOnce(handoffSnapshot)
      .mockResolvedValue(completedSnapshot);
    renderSurface();
    expect(await screen.findByText("先确认目标，")).toBeInTheDocument();

    emitStreamEvent({ kind: "turn_updated" });
    await waitFor(() => expect(api.fetchTutorConversationSnapshot).toHaveBeenCalledTimes(2));
    const preservedThinking = document.querySelector(".tutor-thinking-text");
    expect(preservedThinking).not.toBeNull();
    expect(preservedThinking?.textContent).not.toBe("");
    expect(screen.getByRole("button", { name: "Think" })).toHaveAttribute("aria-expanded", "true");

    emitStreamEvent({ kind: "item_added" });
    await waitFor(() => expect(api.fetchTutorConversationSnapshot).toHaveBeenCalledTimes(3));
    const disclosure = screen.getByRole("button", { name: "Think" });
    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    expect(screen.queryByText(finalThinking)).not.toBeInTheDocument();

    expect(await screen.findByText(finalThinking, {}, { timeout: 2_000 })).toBeInTheDocument();
    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByText(finalAnswer, {}, { timeout: 2_000 })).toBeInTheDocument();
    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    await waitFor(() => expect(disclosure).toHaveAttribute("aria-expanded", "false"), { timeout: 2_000 });

    await user.click(disclosure);
    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    emitStreamEvent({ kind: "turn_updated" });
    await waitFor(() => expect(api.fetchTutorConversationSnapshot).toHaveBeenCalledTimes(4));
    expect(disclosure).toHaveAttribute("aria-expanded", "true");
  });

  it("renders historical Think as plain text, collapsed by default, and supports keyboard expansion", async () => {
    const user = userEvent.setup();
    api.fetchTutorConversationSnapshot.mockResolvedValue({
      ...snapshot,
      conversation: { ...snapshot.conversation, control_state: "idle", pending_count: 0, queue_paused: false, queue_pause_reason: null },
      active_turn: null,
      active_thinking: null,
      pending_requests: [],
      queue: [],
      timeline: [{
        kind: "message", id: "message-tutor", turn_id: "turn-complete", role: "tutor", content: "我们先确定网站目标和最小页面。",
        public_thinking_text: "先确认网站服务的目标用户。\n\n再确定最小页面。", public_thinking_steps: [], context_references: [], in_reply_to_item_id: null, created_at: "2026-08-14T00:00:02Z",
      }],
    });

    renderSurface();

    expect(await screen.findByText("我们先确定网站目标和最小页面。")).toBeInTheDocument();
    const disclosure = screen.getByRole("button", { name: "Think" });
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
    disclosure.focus();
    expect(disclosure).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    expect(screen.queryByRole("status", { name: "Think" })).not.toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });
});
