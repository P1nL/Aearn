import { afterEach, describe, expect, it, vi } from "vitest";
import { acceptTutorConversationInput, retryTutorTurn } from "../api";

const scope = { stimulus_id: "stimulus-1", stimulus_kind: "learner_message", session_id: "session-1",
  checkpoint_id: "checkpoint-1", session_version: 2, track_id: "track-1", knowledge_key: "n1_1", mode: "guided" };
const accepted = { conversation_id: "conversation-1", run_id: "run-1", input_revision: 1, message_id: "message-1",
  event_cursor: 1, dispatch_job_id: "job-1", merged: false, input_replayed: false, idempotent_replayed: false,
  replaced_run_id: null, replaced_process: null, process: null, context_references: [],
  run: { run_id: "run-1", conversation_id: "conversation-1", origin: "interactive", status: "queued",
    input_revision: 1, cancelled: false, iteration_count: 0, model_call_count: 0, capability_call_count: 0,
    effect_count: 0, terminal_outcome: null, continuation_kind: null, interaction_protocol_version: "thread_turn_v2",
    retry_of_turn_id: null, retry_root_turn_id: null, response_to_request_id: null, completion_reason: null,
    created_at: null, updated_at: null } };
const send = (payload: unknown) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), {
    status: 202, headers: { "Content-Type": "application/json" },
  })));
  return acceptTutorConversationInput({ userId: "user-1", conversationId: "conversation-1", content: "answer", clientActionId: "action-1" });
};
afterEach(() => vi.unstubAllGlobals());
describe("accepted teaching input projection", () => {
  it("accepts and preserves the server teaching scope without resubmitting", async () => {
    expect(await send({ ...accepted, teaching_scope: scope })).toMatchObject({ teaching_scope: scope });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("keeps non-teaching inputs compatible", async () => {
    expect(await send(accepted)).toMatchObject({ run_id: "run-1" });
  });
  it.each([null, { ...scope, mode: "unknown" }, { ...scope, session_version: 0 },
    { ...scope, session_id: "" }, { ...scope, unexpected: true }])("rejects malformed scope %j", async (value) => {
    await expect(send({ ...accepted, teaching_scope: value })).rejects.toThrow("invalid payload");
  });
  it("still rejects unknown top-level fields", async () => {
    await expect(send({ ...accepted, unexpected: true })).rejects.toThrow("invalid payload");
  });
});


it("retry response preserves teaching scope with its control version", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...accepted, control_version: 2, teaching_scope: scope }), {
    status: 202, headers: { "Content-Type": "application/json" },
  })));
  const result = await retryTutorTurn({ userId: "user-1", conversationId: "conversation-1", turnId: "failed-1",
    expectedControlVersion: 1, clientActionId: "retry-1" });
  expect(result.teaching_scope).toEqual(scope);
  expect(result.control_version).toBe(2);
  expect(fetch).toHaveBeenCalledTimes(1);
});
