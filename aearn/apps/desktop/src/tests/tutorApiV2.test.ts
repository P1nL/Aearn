import { createHash } from "node:crypto";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  actOnTutorArtifact,
  fetchTutorArtifact,
  fetchTutorArtifactAttempt,
  fetchTutorConversationSnapshot,
  fetchTutorThreadTurnV2Capability,
  mutateTeachingSession,
  openTeachingSession,
} from "../api";

const jsonResponse = (value: unknown) => new Response(JSON.stringify(value), {
  status: 200,
  headers: { "Content-Type": "application/json" },
});

const digest = (value: string) => createHash("sha256").update(value).digest("hex");
const canonicalJson = (value: unknown): string => {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
};
const canonicalDigest = (value: unknown) => digest(canonicalJson(value));

function artifactFixture(input: {
  id: string;
  artifactKind: string;
  purpose: string;
  presentation: Record<string, unknown>;
  overrides?: Record<string, unknown>;
}): Record<string, unknown> {
  return {
    kind: "artifact",
    id: input.id,
    conversation_id: "conversation-1",
    turn_id: null,
    learning_track_id: "track-1",
    knowledge_key: "javascript.variables",
    teaching_session_id: "teaching-session-1",
    checkpoint_id: "checkpoint-1",
    artifact_version: 1,
    artifact_kind: input.artifactKind,
    purpose: input.purpose,
    owner_kind: "teaching_practice",
    owner_id: "checkpoint-1",
    owner_version: 1,
    state: "active",
    blocking: false,
    title: `Artifact ${input.id}`,
    instruction_markdown: "Complete the **server-owned** interaction.",
    difficulty: "D2",
    presentation: input.presentation,
    allowed_actions: [],
    source_references: [{
      kind: "teaching_checkpoint",
      reference_id: "checkpoint-1",
      reference_version: 1,
      content_hash: null,
      label: "Current checkpoint",
    }],
    active_attempt: null,
    branch_summary: null,
    version: 1,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
    terminal_at: null,
    ...input.overrides,
  };
}

function artifactPresentations(): Array<{ artifactKind: string; purpose: string; presentation: Record<string, unknown> }> {
  const sourceCode = "const value = 2;\nconsole.log(value);\n";
  const reviewSource = "const ratio = 0;";
  const reviewCode = "const ratio = total / count;";
  const reviewHunks = [{
    hunk_id: "diff.h1",
    header: "@@ -1,1 +1,1 @@",
    source_start: 1,
    source_count: 1,
    modified_start: 1,
    modified_count: 1,
    lines: [
      { line_key: "h1.l1", kind: "removed", text: reviewSource, source_line: 1, modified_line: null },
      { line_key: "h1.l2", kind: "added", text: reviewCode, source_line: null, modified_line: 1 },
    ],
  }];
  const reviewSourceHash = canonicalDigest({ code: reviewSource });
  const reviewModifiedHash = canonicalDigest({ code: reviewCode });
  const reviewTarget = {
    schema_version: "model_code_review_artifact_v2",
    presentation_mode: "diff",
    language_id: "javascript",
    runtime_label: "Node.js",
    source_code: reviewSource,
    modified_code: reviewCode,
    source_hash: reviewSourceHash,
    modified_hash: reviewModifiedHash,
    diff_hash: canonicalDigest({
      presentation_mode: "diff",
      source_hash: reviewSourceHash,
      modified_hash: reviewModifiedHash,
      hunks: reviewHunks,
    }),
    line_count: 1,
    hunks: reviewHunks,
  };
  return [
    {
      artifactKind: "exercise_workspace",
      purpose: "exercise",
      presentation: {
        type: "exercise_workspace_v1",
        exercise_version_id: "exercise-1",
        language_id: "javascript",
        editor_mode: "code",
        starter_content: "const value = \"变量\";\n",
        starter_content_hash: digest("const value = \"变量\";\n"),
        editable: true,
        live_preview: true,
        runtime_profile_key: "javascript.browser",
      },
    },
    {
      artifactKind: "browser_preview",
      purpose: "demonstration",
      presentation: {
        type: "browser_preview_v1",
        source_artifact_id: "artifact-exercise",
        source_content_hash: digest("const value = \"变量\";\n"),
        experience_tier: "local_non_authoritative",
        interactive: true,
      },
    },
    {
      artifactKind: "test_result",
      purpose: "result",
      presentation: {
        type: "test_result_v1",
        attempt_id: "attempt-1",
        status: "terminal",
        outcome: "passed",
        passed_count: 3,
        total_count: 3,
        summary_markdown: "All visible checks passed.",
        result_hash: digest("result-1"),
      },
    },
    {
      artifactKind: "knowledge_check",
      purpose: "knowledge_check",
      presentation: {
        type: "knowledge_check_v1",
        response_kind: "single_select",
        prompt_markdown: "What value is assigned?",
        options: [{ value: "2", label: "2" }, { value: "3", label: "3" }],
        minimum_selections: 1,
        maximum_selections: 1,
        maximum_text_length: 2_000,
      },
    },
    {
      artifactKind: "model_code_review",
      purpose: "code_review",
      presentation: {
        type: "model_code_review_v1",
        exercise_version_id: "exercise-review-1",
        language_id: "javascript",
        source_code: sourceCode,
        source_code_hash: digest(sourceCode),
        line_count: 2,
        review_categories: ["logic", "contract.integration"],
      },
    },
    {
      artifactKind: "model_code_review",
      purpose: "code_review",
      presentation: {
        type: "model_code_review_v2",
        exercise_version_id: "exercise-review-2",
        presentation_hash: canonicalDigest(reviewTarget),
        review_target: reviewTarget,
        review_categories: [
          "requirements_drift", "fabricated_api", "logic_boundary", "contract_integration",
          "async_lifecycle", "security_trust", "error_false_success",
        ],
        submission_locked: false,
        outcome: null,
        score: null,
        evaluation_markdown: "",
        review_receipt_id: null,
        result_hash: null,
        remediation_handle: null,
      },
    },
    {
      artifactKind: "sql_workspace",
      purpose: "sql_exploration",
      presentation: {
        type: "sql_workspace_v1",
        exercise_version_id: "exercise-sql-1",
        dialect: "sqlite",
        starter_query: "SELECT 1;\n",
        starter_query_hash: digest("SELECT 1;\n"),
        schema_markdown: "`numbers(value INTEGER)`",
        max_rows: 100,
      },
    },
    {
      artifactKind: "demonstration",
      purpose: "demonstration",
      presentation: {
        type: "demonstration_v1",
        demonstration_mode: "static",
        language_id: "javascript",
        source_content: "button.click();",
        source_content_hash: digest("button.click();"),
        expected_event_key: null,
        duration_seconds: 6,
      },
    },
    {
      artifactKind: "source_inspector",
      purpose: "remediation",
      presentation: {
        type: "source_inspector_v1",
        document_id: "document-1",
        document_content_hash: digest("document-1"),
        block_id: "block-1",
        excerpt: "A bounded source excerpt.",
        citation_ids: ["citation-1"],
      },
    },
  ];
}

function artifactAttemptFixture(
  schemaVersion: "tutor_learning_artifact_attempt_v1" | "tutor_learning_artifact_attempt_v2",
): Record<string, unknown> {
  const base = {
    schema_version: schemaVersion,
    artifact_id: "artifact-result",
    artifact_version: 2,
    conversation_id: "conversation-1",
    learning_track_id: "track-1",
    knowledge_key: "javascript.variables",
    teaching_session_id: "teaching-session-1",
    attempt_id: "attempt-1",
    attempt_type: "run",
    exercise_version_id: "exercise-1",
    submission_hash: digest("learner-submission"),
    independence: "independent",
    assistance_kind: "independent",
    status: "terminal",
    execution_job_state: "completed",
    accepted_at: "2026-09-01T00:00:00Z",
  };
  const commonResult = {
    outcome: "failed",
    score: 0.5,
    capability_scores: { correctness: 0.5 },
    policy_version: "artifact.result.v2",
    result_hash: digest("attempt-result"),
    terminal_at: "2026-09-01T00:00:01Z",
  };
  if (schemaVersion === "tutor_learning_artifact_attempt_v1") {
    return { ...base, result: { ...commonResult, safe_feedback: { summary: "Historical learner-safe result." } } };
  }
  return {
    ...base,
    result: {
      ...commonResult,
      execution_result: {
        schema_version: "safe-execution-result-v2",
        status: "success",
        stdout: "query complete",
        stderr: "",
        test_feedback: [
          { case_id: "visible.case", passed: false, visible: true, message: "Returned value did not match.", duration_ms: 7,
            location: { line: 2, column: 3, end_line: 2, end_column: 8 } },
          { case_id: "non-visible-1", passed: true, visible: false, message: "A non-visible scenario passed.", duration_ms: 4, location: null },
        ],
        passed_test_count: 1,
        total_test_count: 2,
        duration_ms: 11,
        diagnostic_code: "visible_test_failure",
        presentation: { kind: "table_result_v1", columns: ["id", "label"], rows: [[1, "alpha"], [2, null]] },
      },
    },
  };
}

const artifactAttemptRequest = {
  userId: "user-1",
  conversationId: "conversation-1",
  artifactId: "artifact-result",
  artifactVersion: 2,
  learningTrackId: "track-1",
  knowledgeKey: "javascript.variables",
  teachingSessionId: "teaching-session-1",
  attemptId: "attempt-1",
} as const;

function snapshotFixture(
  version: "tutor_conversation_snapshot_v2" | "tutor_conversation_snapshot_v3" | "tutor_conversation_snapshot_v4" | "tutor_conversation_snapshot_v5",
  input: { timeline?: unknown[]; activeArtifact?: unknown; branches?: unknown[] } = {},
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    snapshot_version: version,
    conversation: {
      conversation_id: "conversation-1",
      title: "Artifact contract",
      control_version: 2,
      control_state: "idle",
      queue_paused: false,
      queue_pause_reason: null,
      pending_count: 0,
      max_pending: 10,
    },
    active_turn: null,
    active_thinking: null,
    pending_requests: [],
    queue: [],
    timeline: input.timeline ?? [],
    next_cursor: null,
    has_more: false,
    stream_cursor: "opaque.cursor",
  };
  if (version !== "tutor_conversation_snapshot_v2") payload.active_runtime_output = null;
  if (version === "tutor_conversation_snapshot_v4" || version === "tutor_conversation_snapshot_v5") {
    payload.active_artifact = input.activeArtifact ?? null;
  }
  if (version === "tutor_conversation_snapshot_v5") payload.branches = input.branches ?? [];
  return payload;
}

function snapshotMessage(input: { id: string; turnId: string; role: "learner" | "tutor"; content: string }) {
  return {
    kind: "message",
    id: input.id,
    turn_id: input.turnId,
    role: input.role,
    content: input.content,
    public_thinking_text: "",
    public_thinking_steps: [],
    runtime_output: null,
    context_references: [],
    in_reply_to_item_id: null,
    created_at: "2026-09-01T00:01:00Z",
  };
}

function branchSnapshotFixture(): Record<string, unknown> {
  const branchSummary = {
    branch_id: "branch-1",
    state: "resolved",
    disposition: "answer_and_refocus",
    round_count: 1,
    item_count: 3,
    collapsed: true,
  };
  const artifact = artifactFixture({
    id: "artifact-branch",
    artifactKind: "knowledge_check",
    purpose: "knowledge_check",
    presentation: artifactPresentations()[3].presentation,
    overrides: { blocking: true, allowed_actions: ["respond"], branch_summary: branchSummary },
  });
  const learner = snapshotMessage({ id: "message-learner", turnId: "turn-branch", role: "learner", content: "Why?" });
  const process = {
    kind: "process",
    id: "process-branch",
    turn_id: "turn-branch",
    run_id: "turn-branch",
    display_state: "completed",
    steps: [{ key: "input_received", state: "completed", label: "Input received" }],
    elapsed_seconds: 1,
    created_at: "2026-09-01T00:01:00Z",
    finished_at: "2026-09-01T00:01:01Z",
  };
  const tutor = snapshotMessage({ id: "message-tutor", turnId: "turn-branch", role: "tutor", content: "Because assignment binds the evaluated value." });
  const branch = {
    schema_version: "tutor_conversation_branch_v1",
    branch_id: "branch-1",
    anchor_artifact_id: "artifact-branch",
    teaching_session_id: "teaching-session-1",
    checkpoint_id: "checkpoint-1",
    state: "resolved",
    disposition: "answer_and_refocus",
    round_count: 1,
    item_count: 3,
    collapsed: true,
    items: [
      { item_sequence: 1, branch_round: 1, item_kind: "message", item_id: "message-learner", turn_id: "turn-branch", item_role: "learner" },
      { item_sequence: 2, branch_round: 1, item_kind: "process", item_id: "process-branch", turn_id: "turn-branch", item_role: "process" },
      { item_sequence: 3, branch_round: 1, item_kind: "message", item_id: "message-tutor", turn_id: "turn-branch", item_role: "tutor" },
    ],
    created_at: "2026-09-01T00:01:00Z",
    resolved_at: "2026-09-01T00:01:02Z",
  };
  return snapshotFixture("tutor_conversation_snapshot_v5", {
    timeline: [artifact, learner, process, tutor],
    activeArtifact: structuredClone(artifact),
    branches: [branch],
  });
}

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

  it("accepts snapshot v4 with active Artifact and every registered presentation", async () => {
    const artifacts = artifactPresentations().map((item, index) => artifactFixture({
      id: `artifact-${index + 1}`,
      artifactKind: item.artifactKind,
      purpose: item.purpose,
      presentation: item.presentation,
    }));
    artifacts[0] = { ...artifacts[0], blocking: true, allowed_actions: ["run"] };
    artifacts[5] = { ...artifacts[5], allowed_actions: ["complete_review", "cancel"] };
    artifacts[2] = {
      ...artifacts[2],
      state: "completed",
      terminal_at: "2026-09-01T00:00:01Z",
      active_attempt: {
        attempt_id: "attempt-1",
        attempt_type: "run",
        status: "terminal",
        outcome: "passed",
        score: 1,
        result_hash: digest("result-1"),
        accepted_at: "2026-09-01T00:00:00Z",
        terminal_at: "2026-09-01T00:00:01Z",
      },
      source_references: [{
        kind: "artifact",
        reference_id: "artifact-1",
        reference_version: 1,
        content_hash: null,
        label: "Source Artifact",
      }, {
        kind: "attempt_result",
        reference_id: "attempt-1",
        reference_version: null,
        content_hash: digest("result-1"),
        label: "Authoritative Attempt result",
      }],
    };
    const payload = snapshotFixture("tutor_conversation_snapshot_v4", {
      timeline: artifacts,
      activeArtifact: structuredClone(artifacts[0]),
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(payload)));

    const snapshot = await fetchTutorConversationSnapshot({ userId: "user-1", conversationId: "conversation-1" });

    expect(snapshot.snapshot_version).toBe("tutor_conversation_snapshot_v4");
    expect(snapshot.active_artifact?.id).toBe("artifact-1");
    expect(snapshot.branches).toEqual([]);
    expect(snapshot.timeline.filter((item) => item.kind === "artifact").map((item) => item.presentation.type)).toEqual([
      "exercise_workspace_v1",
      "browser_preview_v1",
      "test_result_v1",
      "knowledge_check_v1",
      "model_code_review_v1",
      "model_code_review_v2",
      "sql_workspace_v1",
      "demonstration_v1",
      "source_inspector_v1",
    ]);
  });

  it("accepts snapshot v5 with exact depth-one branch groups and timeline identity", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(branchSnapshotFixture())));

    const snapshot = await fetchTutorConversationSnapshot({ userId: "user-1", conversationId: "conversation-1" });

    expect(snapshot.snapshot_version).toBe("tutor_conversation_snapshot_v5");
    expect(snapshot.active_artifact).toMatchObject({ id: "artifact-branch", branch_summary: { branch_id: "branch-1", item_count: 3 } });
    expect(snapshot.branches).toEqual([expect.objectContaining({
      branch_id: "branch-1",
      state: "resolved",
      disposition: "answer_and_refocus",
      collapsed: true,
      items: [
        expect.objectContaining({ item_sequence: 1, item_role: "learner" }),
        expect.objectContaining({ item_sequence: 2, item_role: "process" }),
        expect.objectContaining({ item_sequence: 3, item_role: "tutor" }),
      ],
    })]);
  });

  it("normalizes snapshot v2 and v3 compatibility fields without accepting newer keys", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(snapshotFixture("tutor_conversation_snapshot_v2")))
      .mockResolvedValueOnce(jsonResponse(snapshotFixture("tutor_conversation_snapshot_v3")));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchTutorConversationSnapshot({ userId: "user-1", conversationId: "conversation-1" })).resolves.toMatchObject({
      snapshot_version: "tutor_conversation_snapshot_v2",
      active_runtime_output: null,
      active_artifact: null,
      branches: [],
    });
    await expect(fetchTutorConversationSnapshot({ userId: "user-1", conversationId: "conversation-1" })).resolves.toMatchObject({
      snapshot_version: "tutor_conversation_snapshot_v3",
      active_runtime_output: null,
      active_artifact: null,
      branches: [],
    });
  });
  it("rejects reserved private markers anywhere in a public snapshot", async () => {
    const message = snapshotMessage({ id: "message-private-marker", turnId: "turn-private-marker", role: "tutor", content: "__AEARN_PROVIDER_REASONING__" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(
      snapshotFixture("tutor_conversation_snapshot_v3", { timeline: [message] }),
    )));

    await expect(fetchTutorConversationSnapshot({ userId: "user-1", conversationId: "conversation-1" }))
      .rejects.toThrow("Tutor snapshot API returned an invalid payload");
  });

  it("reads exact Artifact detail and validates scoped Artifact action responses", async () => {
    const active = artifactFixture({
      id: "artifact-action",
      artifactKind: "knowledge_check",
      purpose: "knowledge_check",
      presentation: artifactPresentations()[3].presentation,
      overrides: { allowed_actions: ["cancel"] },
    });
    const cancelled = {
      ...active,
      state: "cancelled",
      allowed_actions: [],
      version: 2,
      updated_at: "2026-09-01T00:02:00Z",
      terminal_at: "2026-09-01T00:02:00Z",
    };
    const terminalRunProjection = {
      ...cancelled,
      version: 3,
      updated_at: "2026-09-01T00:02:01Z",
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(active))
      .mockResolvedValueOnce(jsonResponse({
        artifact: cancelled,
        artifact_event_id: "artifact-event-2",
        artifact_event_sequence: 2,
        idempotent_replayed: false,
      }))
      .mockResolvedValueOnce(jsonResponse({
        artifact: terminalRunProjection,
        artifact_event_id: "artifact-event-3",
        artifact_event_sequence: 3,
        idempotent_replayed: false,
      }))
      .mockResolvedValueOnce(jsonResponse({
        artifact: cancelled,
        artifact_event_id: "artifact-event-2",
        artifact_event_sequence: 1,
        idempotent_replayed: false,
      }))
      .mockResolvedValueOnce(jsonResponse({
        artifact: cancelled,
        artifact_event_id: "artifact-event-2",
        artifact_event_sequence: 2,
        idempotent_replayed: false,
        dispatch_job_id: "private-continuation-detail",
      }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchTutorArtifact({ userId: "user-1", conversationId: "conversation-1", artifactId: "artifact-action" })).resolves.toMatchObject({
      id: "artifact-action",
      presentation: { type: "knowledge_check_v1" },
    });
    await expect(actOnTutorArtifact({
      userId: "user-1",
      conversationId: "conversation-1",
      artifactId: "artifact-action",
      learningTrackId: "track-1",
      teachingSessionId: "teaching-session-1",
      expectedArtifactVersion: 1,
      action: { action: "cancel", reason: "learner_cancelled" },
      clientActionId: "artifact-action:test",
    })).resolves.toMatchObject({ artifact: { state: "cancelled", version: 2 }, artifact_event_sequence: 2 });
    await expect(actOnTutorArtifact({
      userId: "user-1",
      conversationId: "conversation-1",
      artifactId: "artifact-action",
      learningTrackId: "track-1",
      teachingSessionId: "teaching-session-1",
      expectedArtifactVersion: 1,
      action: { action: "run", submission: "print(1)" },
      clientActionId: "artifact-action:terminal-run",
    })).resolves.toMatchObject({ artifact: { version: 3 }, artifact_event_sequence: 3 });
    await expect(actOnTutorArtifact({
      userId: "user-1",
      conversationId: "conversation-1",
      artifactId: "artifact-action",
      learningTrackId: "track-1",
      teachingSessionId: "teaching-session-1",
      expectedArtifactVersion: 1,
      action: { action: "cancel", reason: "learner_cancelled" },
      clientActionId: "artifact-action:bad-response",
    })).rejects.toThrow("Tutor Artifact action API returned an invalid payload");
    await expect(actOnTutorArtifact({
      userId: "user-1",
      conversationId: "conversation-1",
      artifactId: "artifact-action",
      learningTrackId: "track-1",
      teachingSessionId: "teaching-session-1",
      expectedArtifactVersion: 1,
      action: { action: "cancel", reason: "learner_cancelled" },
      clientActionId: "artifact-action:extra-response",
    })).rejects.toThrow("Tutor Artifact action API returned an invalid payload");

    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("http://127.0.0.1:8001/api/tutor/conversations/conversation-1/artifacts/artifact-action?user_id=user-1");
    expect(fetchMock.mock.calls[1]?.[1]?.headers).toMatchObject({ "Idempotency-Key": "artifact-action:test" });
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({
      user_id: "user-1",
      learning_track_id: "track-1",
      teaching_session_id: "teaching-session-1",
      client_action_id: "artifact-action:test",
      expected_artifact_version: 1,
      action: { action: "cancel", reason: "learner_cancelled" },
    });
  });

  it("reads historical Attempt v1 and strict scoped Attempt v2 results", async () => {
    const v1 = artifactAttemptFixture("tutor_learning_artifact_attempt_v1");
    const v2 = artifactAttemptFixture("tutor_learning_artifact_attempt_v2");
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(v1))
      .mockResolvedValueOnce(jsonResponse(v2));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchTutorArtifactAttempt(artifactAttemptRequest)).resolves.toMatchObject({
      schema_version: "tutor_learning_artifact_attempt_v1",
      result: { safe_feedback: { summary: "Historical learner-safe result." } },
    });
    await expect(fetchTutorArtifactAttempt(artifactAttemptRequest)).resolves.toMatchObject({
      schema_version: "tutor_learning_artifact_attempt_v2",
      result: {
        execution_result: {
          schema_version: "safe-execution-result-v2",
          presentation: { kind: "table_result_v1", columns: ["id", "label"], rows: [[1, "alpha"], [2, null]] },
        },
      },
    });
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "http://127.0.0.1:8001/api/tutor/conversations/conversation-1/artifacts/artifact-result/attempts/attempt-1?user_id=user-1",
    );
  });

  it("round-trips backend character bounds for astral execution text", async () => {
    const payload = artifactAttemptFixture("tutor_learning_artifact_attempt_v2");
    const result = (payload.result as Record<string, unknown>).execution_result as Record<string, unknown>;
    result.stdout = "😀".repeat(4_000);
    result.presentation = {
      kind: "table_result_v1",
      columns: ["😀".repeat(120)],
      rows: [["😀".repeat(500)]],
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(payload)));

    const detail = await fetchTutorArtifactAttempt(artifactAttemptRequest);

    expect(detail.schema_version).toBe("tutor_learning_artifact_attempt_v2");
    if (detail.schema_version !== "tutor_learning_artifact_attempt_v2") return;
    expect(Array.from(detail.result?.execution_result?.stdout ?? "")).toHaveLength(4_000);
    const presentation = detail.result?.execution_result?.presentation;
    expect(presentation?.kind).toBe("table_result_v1");
  });

  it("rejects extra, mixed, protected, bad-count, bad-location, hidden-id, table-bound, and scope-invalid Attempt v2 payloads", async () => {
    const exact = artifactAttemptFixture("tutor_learning_artifact_attempt_v2");
    const extra = { ...structuredClone(exact), provider_metadata: "private" };
    const mixed = structuredClone(exact);
    (mixed.result as Record<string, unknown>).safe_feedback = {};
    const protectedOutput = structuredClone(exact);
    (((protectedOutput.result as Record<string, unknown>).execution_result as Record<string, unknown>)).stdout = "/workspace/secret.py";
    const badCount = structuredClone(exact);
    (((badCount.result as Record<string, unknown>).execution_result as Record<string, unknown>)).passed_test_count = 3;
    const badLocation = structuredClone(exact);
    (((((badLocation.result as Record<string, unknown>).execution_result as Record<string, unknown>).test_feedback as Array<Record<string, unknown>>)[0].location as Record<string, unknown>)).end_line = null;
    const hiddenId = structuredClone(exact);
    (((((hiddenId.result as Record<string, unknown>).execution_result as Record<string, unknown>).test_feedback as Array<Record<string, unknown>>)[1])).case_id = "hidden-real-case";
    const badTable = structuredClone(exact);
    (((badTable.result as Record<string, unknown>).execution_result as Record<string, unknown>)).presentation = {
      kind: "table_result_v1",
      columns: ["id", "label"],
      rows: [[1]],
    };
    const tooManyRows = structuredClone(exact);
    (((tooManyRows.result as Record<string, unknown>).execution_result as Record<string, unknown>)).presentation = {
      kind: "table_result_v1",
      columns: ["id"],
      rows: Array.from({ length: 201 }, (_, index) => [index]),
    };
    const unsafeNumber = structuredClone(exact);
    (((unsafeNumber.result as Record<string, unknown>).execution_result as Record<string, unknown>)).presentation = {
      kind: "table_result_v1",
      columns: ["id"],
      rows: [[Number.MAX_SAFE_INTEGER + 1]],
    };
    const wrongScope = { ...structuredClone(exact), learning_track_id: "track-other" };
    const variants = [extra, mixed, protectedOutput, badCount, badLocation, hiddenId, badTable, tooManyRows, unsafeNumber, wrongScope];
    const fetchMock = vi.fn();
    variants.forEach((variant) => fetchMock.mockResolvedValueOnce(jsonResponse(variant)));
    vi.stubGlobal("fetch", fetchMock);

    for (const _variant of variants) {
      await expect(fetchTutorArtifactAttempt(artifactAttemptRequest))
        .rejects.toThrow("Tutor Artifact Attempt API returned an invalid payload");
    }
  });

  it("rejects unknown, extra, protected, and kind-mismatched Artifact fields", async () => {
    const base = artifactFixture({
      id: "artifact-invalid",
      artifactKind: "knowledge_check",
      purpose: "knowledge_check",
      presentation: artifactPresentations()[3].presentation,
    });
    const variants = [
      { ...base, presentation: { type: "unknown_presentation_v1" } },
      { ...base, provider_body: { secret: true } },
      { ...base, title: "__AEARN_PRIVATE_SUBMISSION__" },
      { ...base, artifact_kind: "sql_workspace" },
      { ...base, allowed_actions: ["future_action"] },
    ];
    const fetchMock = vi.fn();
    variants.forEach((variant) => fetchMock.mockResolvedValueOnce(jsonResponse(
      snapshotFixture("tutor_conversation_snapshot_v4", { timeline: [variant] }),
    )));
    vi.stubGlobal("fetch", fetchMock);

    for (const _variant of variants) {
      await expect(fetchTutorConversationSnapshot({ userId: "user-1", conversationId: "conversation-1" }))
        .rejects.toThrow("Tutor snapshot API returned an invalid payload");
    }
  });

  it("rejects duplicate Artifact identities and cross-scope projection mismatches", async () => {
    const base = artifactFixture({
      id: "artifact-identity",
      artifactKind: "knowledge_check",
      purpose: "knowledge_check",
      presentation: artifactPresentations()[3].presentation,
    });
    const duplicateActions = { ...base, allowed_actions: ["respond", "respond"] };
    const sourceReferences = base.source_references as unknown[];
    const duplicateReferences = { ...base, source_references: [sourceReferences[0], structuredClone(sourceReferences[0])] };
    const blocking = { ...base, blocking: true, allowed_actions: ["respond"] };
    const snapshots = [
      snapshotFixture("tutor_conversation_snapshot_v4", { timeline: [duplicateActions] }),
      snapshotFixture("tutor_conversation_snapshot_v4", { timeline: [duplicateReferences] }),
      snapshotFixture("tutor_conversation_snapshot_v4", { timeline: [base, structuredClone(base)] }),
      snapshotFixture("tutor_conversation_snapshot_v4", { timeline: [blocking], activeArtifact: { ...blocking, version: 2 } }),
      snapshotFixture("tutor_conversation_snapshot_v4", { timeline: [{ ...base, conversation_id: "conversation-foreign" }] }),
    ];
    const fetchMock = vi.fn();
    snapshots.forEach((snapshot) => fetchMock.mockResolvedValueOnce(jsonResponse(snapshot)));
    vi.stubGlobal("fetch", fetchMock);

    for (const _snapshot of snapshots) {
      await expect(fetchTutorConversationSnapshot({ userId: "user-1", conversationId: "conversation-1" }))
        .rejects.toThrow("Tutor snapshot API returned an invalid payload");
    }
  });

  it("rejects bad Artifact hashes, counts, and terminal shapes", async () => {
    const presentations = artifactPresentations();
    const badHash = artifactFixture({
      id: "artifact-bad-hash",
      artifactKind: "exercise_workspace",
      purpose: "exercise",
      presentation: { ...presentations[0].presentation, starter_content_hash: "0".repeat(64) },
    });
    const badCounts = artifactFixture({
      id: "artifact-bad-counts",
      artifactKind: "test_result",
      purpose: "result",
      presentation: { ...presentations[2].presentation, passed_count: 4, total_count: 3 },
    });
    const badPresentationTerminal = artifactFixture({
      id: "artifact-bad-result-terminal",
      artifactKind: "test_result",
      purpose: "result",
      presentation: { ...presentations[2].presentation, result_hash: null },
    });
    const badAttemptTerminal = artifactFixture({
      id: "artifact-bad-attempt-terminal",
      artifactKind: "knowledge_check",
      purpose: "knowledge_check",
      presentation: presentations[3].presentation,
      overrides: {
        active_attempt: {
          attempt_id: "attempt-2",
          attempt_type: "run",
          status: "terminal",
          outcome: "passed",
          score: null,
          result_hash: digest("attempt-2"),
          accepted_at: "2026-09-01T00:00:00Z",
          terminal_at: "2026-09-01T00:00:01Z",
        },
      },
    });
    const badArtifactTerminal = artifactFixture({
      id: "artifact-bad-artifact-terminal",
      artifactKind: "knowledge_check",
      purpose: "knowledge_check",
      presentation: presentations[3].presentation,
      overrides: { state: "completed", allowed_actions: ["respond"], terminal_at: null },
    });
    const badLineCount = artifactFixture({
      id: "artifact-bad-line-count",
      artifactKind: "model_code_review",
      purpose: "code_review",
      presentation: { ...presentations[4].presentation, line_count: 3 },
    });
    const reviewV2 = presentations[5].presentation;
    const failedWithoutRemediation = artifactFixture({
      id: "artifact-review-missing-remediation",
      artifactKind: "model_code_review",
      purpose: "code_review",
      presentation: {
        ...reviewV2,
        submission_locked: true,
        outcome: "failed",
        score: 0.4,
        evaluation_markdown: "Server evaluation requires remediation.",
        review_receipt_id: "receipt-review",
        result_hash: digest("review-result"),
      },
      overrides: { state: "completed", allowed_actions: [], terminal_at: "2026-09-02T00:00:01Z" },
    });
    const terminalReviewInActiveArtifact = artifactFixture({
      id: "artifact-review-active-terminal",
      artifactKind: "model_code_review",
      purpose: "code_review",
      presentation: {
        ...reviewV2,
        submission_locked: true,
        outcome: "passed",
        score: 1,
        evaluation_markdown: "Server evaluation passed.",
        review_receipt_id: "receipt-review",
        result_hash: digest("review-result"),
      },
    });
    const missingReviewAction = artifactFixture({
      id: "artifact-review-missing-action",
      artifactKind: "model_code_review",
      purpose: "code_review",
      presentation: reviewV2,
      overrides: { allowed_actions: ["cancel"] },
    });
    const malformedReview = (
      id: string,
      mutate: (target: Record<string, unknown>, hunk: Record<string, unknown>, lines: Array<Record<string, unknown>>) => void,
    ) => {
      const presentation = structuredClone(reviewV2) as Record<string, unknown>;
      const target = presentation.review_target as Record<string, unknown>;
      const hunks = target.hunks as Array<Record<string, unknown>>;
      const hunk = hunks[0];
      const lines = hunk.lines as Array<Record<string, unknown>>;
      mutate(target, hunk, lines);
      target.diff_hash = canonicalDigest({
        presentation_mode: target.presentation_mode,
        source_hash: target.source_hash,
        modified_hash: target.modified_hash,
        hunks,
      });
      presentation.presentation_hash = canonicalDigest(target);
      return artifactFixture({
        id,
        artifactKind: "model_code_review",
        purpose: "code_review",
        presentation,
        overrides: { allowed_actions: ["complete_review", "cancel"] },
      });
    };
    const badReviewText = malformedReview("artifact-review-bad-text", (_target, _hunk, lines) => {
      lines[0].text = "not the published code";
    });
    const badReviewLine = malformedReview("artifact-review-bad-line", (_target, _hunk, lines) => {
      lines[0].source_line = 99;
    });
    const badReviewHeader = malformedReview("artifact-review-bad-header", (_target, hunk) => {
      hunk.header = "@@ bogus @@";
    });
    const badReviewCount = malformedReview("artifact-review-bad-count", (_target, hunk) => {
      hunk.source_count = 2;
    });
    const badReviewLineKey = malformedReview("artifact-review-bad-line-key", (_target, _hunk, lines) => {
      lines[0].line_key = "code.m99";
    });
    const protectedReview = artifactFixture({
      id: "artifact-review-protected",
      artifactKind: "model_code_review",
      purpose: "code_review",
      presentation: { ...reviewV2, private_rubric: { expected_findings: [] } },
      overrides: { allowed_actions: ["complete_review", "cancel"] },
    });
    const variants = [
      badHash, badCounts, badPresentationTerminal, badAttemptTerminal, badArtifactTerminal,
      badLineCount, failedWithoutRemediation, terminalReviewInActiveArtifact, missingReviewAction,
      badReviewText, badReviewLine, badReviewHeader, badReviewCount, badReviewLineKey, protectedReview,
    ];
    const fetchMock = vi.fn();
    variants.forEach((variant) => fetchMock.mockResolvedValueOnce(jsonResponse(
      snapshotFixture("tutor_conversation_snapshot_v4", { timeline: [variant] }),
    )));
    vi.stubGlobal("fetch", fetchMock);

    for (const _variant of variants) {
      await expect(fetchTutorConversationSnapshot({ userId: "user-1", conversationId: "conversation-1" }))
        .rejects.toThrow("Tutor snapshot API returned an invalid payload");
    }
  });

  it("rejects branch duplicates, non-contiguous membership, bad counts, and timeline identity mismatch", async () => {
    const variants: Record<string, unknown>[] = [];
    const duplicateBranches = branchSnapshotFixture();
    duplicateBranches.branches = [
      structuredClone((duplicateBranches.branches as unknown[])[0]),
      structuredClone((duplicateBranches.branches as unknown[])[0]),
    ];
    variants.push(duplicateBranches);

    const nonContiguous = branchSnapshotFixture();
    ((nonContiguous.branches as Array<Record<string, unknown>>)[0].items as Array<Record<string, unknown>>)[1].item_sequence = 3;
    variants.push(nonContiguous);

    const badCount = branchSnapshotFixture();
    (badCount.branches as Array<Record<string, unknown>>)[0].item_count = 2;
    variants.push(badCount);

    const badResolvedShape = branchSnapshotFixture();
    (badResolvedShape.branches as Array<Record<string, unknown>>)[0].collapsed = false;
    variants.push(badResolvedShape);

    const badRole = branchSnapshotFixture();
    ((badRole.branches as Array<Record<string, unknown>>)[0].items as Array<Record<string, unknown>>)[1].item_role = "tutor";
    variants.push(badRole);

    const badIdentity = branchSnapshotFixture();
    ((badIdentity.branches as Array<Record<string, unknown>>)[0].items as Array<Record<string, unknown>>)[0].turn_id = "turn-other";
    variants.push(badIdentity);

    const badSummary = branchSnapshotFixture();
    ((badSummary.timeline as Array<Record<string, unknown>>)[0].branch_summary as Record<string, unknown>).item_count = 2;
    (badSummary.active_artifact as Record<string, unknown>).branch_summary = structuredClone(
      (badSummary.timeline as Array<Record<string, unknown>>)[0].branch_summary,
    );
    variants.push(badSummary);
    const missingSummary = branchSnapshotFixture();
    (missingSummary.timeline as Array<Record<string, unknown>>)[0].branch_summary = null;
    (missingSummary.active_artifact as Record<string, unknown>).branch_summary = null;
    variants.push(missingSummary);

    const fetchMock = vi.fn();
    variants.forEach((variant) => fetchMock.mockResolvedValueOnce(jsonResponse(variant)));
    vi.stubGlobal("fetch", fetchMock);

    for (const _variant of variants) {
      await expect(fetchTutorConversationSnapshot({ userId: "user-1", conversationId: "conversation-1" }))
        .rejects.toThrow("Tutor snapshot API returned an invalid payload");
    }
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
    const mutated = await mutateTeachingSession({ userId: "user-1", trackId: session.track_id, sessionId: session.session_id, controlKey: "switch_mode",
      expectedSessionVersion: 1, expectedTrackVersion: 3, expectedProgressVersion: 2, expectedAssignmentVersion: 2,
      targetMode: "free_reading", clientActionId: "switch:test" });
    expect(mutated.teaching_session.action_shelf).toMatchObject({ primary_action: null, secondary_actions: [], overflow_actions: [] });
    expect(mutated.teaching_session.allowed_actions).toEqual([]);

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
