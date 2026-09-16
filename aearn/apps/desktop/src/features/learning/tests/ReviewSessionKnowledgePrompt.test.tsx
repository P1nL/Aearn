import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LearningTrackDetail, ReviewAttempt, ReviewExercise, ReviewQueue, ReviewSession } from "../../../types";
import { ReviewSessionPanel } from "../ReviewSessionPanel";

const api = vi.hoisted(() => ({
  createReviewAttempt: vi.fn(), createReviewSession: vi.fn(), fetchReviewAttempt: vi.fn(),
  fetchReviewSession: vi.fn(), finalizeReviewSession: vi.fn(), recordReviewWarmup: vi.fn(), requestReviewHint: vi.fn(),
}));
vi.mock("../../../api", () => api);

const track: LearningTrackDetail = {
  track_id: "track-review", language_id: "python", language_display_name: "Python", goal_text: "练习变量",
  target_level: "beginner", status: "active", version: 3, active_revision_id: "revision-review", active_plan_title: "变量复习",
  current_knowledge_key: "python.variables", current_knowledge_title: "变量",
  progress: { total: 1, completed: 1, in_progress: 0, review_due: 1, percent: 100 }, review_due_count: 1,
  execution_tier: "static_only", execution_disclosure: "静态检查", last_learned_at: null, updated_at: null,
  created_at: null, archived_at: null,
};
const queue: ReviewQueue = { track_id: track.track_id, as_of: null, due_count: 0, items: [], critical_prerequisite_gate: null };
const options = [{ option_id: "choice-draft", label: "draft" }, { option_id: "choice-published", label: "published" }];
type StaticExercise = Extract<ReviewExercise, { exercise_type: Exclude<ReviewExercise["exercise_type"], "model_code_review"> }>;

function knowledgeExercise(responseKind = "prediction", choices: unknown = []): StaticExercise {
  return {
    exercise_version_id: "exercise-review-v1", title: "变量迁移检查", exercise_type: "static_code_reasoning",
    learner_prompt: {
      schema_version: "knowledge_check_prompt_v1", response_kind: responseKind, options: choices,
      prompt_markdown: 'What does this program print?\n\n```python\nlabel = "draft"\nprint(label)\n```',
    },
    starter_artifact: { schema_version: "knowledge_check_artifact_v1", response_kind: responseKind, options: choices },
    required_capabilities: ["python"], content_hash: "a".repeat(64), execution_tier: "static_only", execution_disclosure: "此题未运行代码。",
  };
}
function sessionFor(exercise: ReviewExercise): ReviewSession {
  return {
    session_id: "session-review", track_id: track.track_id, knowledge_key: "python.variables", plan_revision_id: "revision-review",
    state: "active", stage: "practice", failure_code: null, recoverable: false, version: 7,
    context_snapshot: {}, context_snapshot_hash: "b".repeat(64),
    items: [{ item_id: "item-review", order_index: 0, version: 4, exercise, attempt: null }],
    finalization: null, started_at: null, terminal_at: null, idempotent_replayed: false,
  };
}
const attempt: ReviewAttempt = {
  attempt_id: "attempt-review", attempt_type: "review_submit", track_id: track.track_id, session_id: "session-review",
  item_id: "item-review", knowledge_key: "python.variables", session_version: 8, exercise_version_id: "exercise-review-v1",
  submission_hash: "c".repeat(64), independence: "independent", assistance_kind: "independent", accepted_at: null,
  status: "terminal", execution_job_id: null, execution_job_state: null, result: null, idempotent_replayed: false,
};

beforeEach(() => {
  vi.resetAllMocks();
  api.createReviewAttempt.mockResolvedValue(attempt);
  api.requestReviewHint.mockResolvedValue({ hint_id: "hint-review", hint_level: 1, safe_hint: { message: "观察名称对应的值。" }, created_at: null });
});
async function renderReview(exercise = knowledgeExercise()) {
  const session = sessionFor(exercise);
  api.fetchReviewSession.mockResolvedValue(session);
  render(<ReviewSessionPanel userId="user-review" track={track} queue={queue} initialSessionId={session.session_id} onContextReference={vi.fn()} />);
  await screen.findByRole("button", { name: "提交复习答案" });
  return session;
}
async function expectStringSubmission(submission: string) {
  fireEvent.click(screen.getByRole("button", { name: "提交复习答案" }));
  await waitFor(() => expect(api.createReviewAttempt).toHaveBeenCalledTimes(1));
  expect(api.createReviewAttempt).toHaveBeenCalledWith({
    userId: "user-review", trackId: track.track_id, sessionId: "session-review", itemId: "item-review",
    submission, expectedSessionVersion: 7, expectedItemVersion: 4, clientActionId: expect.stringMatching(/^review-attempt:/),
  });
  await waitFor(() => expect(screen.getByRole("button", { name: "提交复习答案" })).toBeEnabled());
}

describe("ReviewSessionPanel knowledge prompts", () => {
  it.each([["prediction", "你的预测"], ["short_text", "你的回答"]])("renders %s Markdown/code and submits the original text", async (kind, label) => {
    await renderReview(knowledgeExercise(kind));
    expect(screen.getByText("What does this program print?")).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.tagName === "CODE" && element.textContent?.includes('label = "draft"') === true)).toBeInTheDocument();
    const input = screen.getByRole("textbox", { name: label });
    expect(input).toHaveValue("");
    expect(screen.getByRole("button", { name: "提交复习答案" })).toBeDisabled();
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "提交复习答案" }));
    expect(api.createReviewAttempt).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "  my answer\nsecond line  " } });
    await expectStringSubmission("  my answer\nsecond line  ");
  });

  it.each(["single_choice", "single_select"])("renders %s radios and submits option_id rather than label or JSON", async (kind) => {
    await renderReview(knowledgeExercise(kind, options));
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: "请选择一个答案" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "提交复习答案" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "提交复习答案" }));
    expect(api.createReviewAttempt).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("radio", { name: "draft" }));
    fireEvent.click(screen.getByRole("radio", { name: "published" }));
    expect(screen.getByRole("radio", { name: "draft" })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: "published" })).toBeChecked();
    await expectStringSubmission("choice-published");
  });

  it("accepts the existing maximum of twelve unique options", async () => {
    await renderReview(knowledgeExercise("single_choice", Array.from({ length: 12 }, (_, i) => ({ option_id: `id-${i}`, label: `option ${i}` }))));
    expect(screen.getAllByRole("radio")).toHaveLength(12);
    fireEvent.click(screen.getByRole("radio", { name: "option 11" }));
    await expectStringSubmission("id-11");
  });

  const invalidCases: Array<[string, (exercise: StaticExercise) => void]> = [
    ["unsupported response kind", (e) => { e.learner_prompt.response_kind = e.starter_artifact.response_kind = "multiple_choice"; }],
    ["unknown prompt schema", (e) => { e.learner_prompt.schema_version = "knowledge_check_prompt_v2"; }],
    ["both unknown schemas", (e) => { e.learner_prompt.schema_version = "unknown_prompt"; e.starter_artifact.schema_version = "unknown_artifact"; }],
    ["missing both schema tags", (e) => { delete e.learner_prompt.schema_version; delete e.starter_artifact.schema_version; }],
    ["mismatched response kinds", (e) => { e.starter_artifact.response_kind = "single_select"; }],
    ["mismatched option labels", (e) => { e.starter_artifact.options = [{ ...options[0], label: "changed" }, options[1]]; }],
    ["mismatched option ids", (e) => { e.starter_artifact.options = [{ ...options[0], option_id: "other" }, options[1]]; }],
    ["mismatched option order", (e) => { e.starter_artifact.options = [...options].reverse(); }],
    ["extra prompt key", (e) => { e.learner_prompt.extra = true; }],
    ["extra artifact key", (e) => { e.starter_artifact.content = "pre-filled answer"; }],
    ["duplicate ids", (e) => { e.learner_prompt.options = e.starter_artifact.options = [options[0], options[0]]; }],
    ["fewer than two options", (e) => { e.learner_prompt.options = e.starter_artifact.options = [options[0]]; }],
    ["more than twelve options", (e) => { e.learner_prompt.options = e.starter_artifact.options = Array.from({ length: 13 }, (_, i) => ({ option_id: `id-${i}`, label: `option ${i}` })); }],
    ["nonempty text options", (e) => { e.learner_prompt.response_kind = e.starter_artifact.response_kind = "short_text"; }],
    ["nonempty prediction options", (e) => { e.learner_prompt.response_kind = e.starter_artifact.response_kind = "prediction"; }],
    ["extra option key", (e) => { e.learner_prompt.options = e.starter_artifact.options = [{ ...options[0], extra: true }, options[1]]; }],
    ["null option", (e) => { e.learner_prompt.options = e.starter_artifact.options = [null, options[1]]; }],
    ["options not an array", (e) => { e.learner_prompt.options = e.starter_artifact.options = {}; }],
    ["empty option id", (e) => { e.learner_prompt.options = e.starter_artifact.options = [{ ...options[0], option_id: " " }, options[1]]; }],
    ["empty option label", (e) => { e.learner_prompt.options = e.starter_artifact.options = [{ ...options[0], label: " " }, options[1]]; }],
    ["empty Markdown", (e) => { e.learner_prompt.prompt_markdown = " "; }],
  ];
  it.each(invalidCases)("fails closed for %s without hint or attempt API calls", async (_, corrupt) => {
    const exercise = knowledgeExercise("single_choice", options);
    corrupt(exercise);
    await renderReview(exercise);
    expect(screen.getByRole("alert")).toHaveTextContent("公开回答格式暂不受支持");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    const submit = screen.getByRole("button", { name: "提交复习答案" });
    const hint = screen.getByRole("button", { name: "渐进提示" });
    expect(submit).toBeDisabled();
    expect(hint).toBeDisabled();
    fireEvent.click(submit);
    fireEvent.click(hint);
    expect(api.createReviewAttempt).not.toHaveBeenCalled();
    expect(api.requestReviewHint).not.toHaveBeenCalled();
    expect(api.createReviewSession).not.toHaveBeenCalled();
  });

  it.each(["message", "text", "summary"])("preserves a legacy %s prompt and its starter text", async (field) => {
    const exercise = knowledgeExercise();
    exercise.learner_prompt = { [field]: "Legacy practice instruction" };
    exercise.starter_artifact = { content: "legacy starter" };
    await renderReview(exercise);
    expect(screen.getByText("Legacy practice instruction")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("textbox", { name: "你的回答" })).toHaveValue("legacy starter"));
    await expectStringSubmission("legacy starter");
  });

  it("preserves versioned legacy text prompts without knowledge-check fields", async () => {
    const exercise = knowledgeExercise();
    exercise.learner_prompt = { schema_version: "legacy_text_v1", message: "Versioned legacy instruction" };
    exercise.starter_artifact = { schema_version: "legacy_text_artifact_v1", content: "legacy answer" };
    await renderReview(exercise);
    expect(screen.getByText("Versioned legacy instruction")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("textbox", { name: "你的回答" })).toHaveValue("legacy answer"));
    await expectStringSubmission("legacy answer");
  });

  it("clears the previous answer when the existing exercise-version transition occurs", async () => {
    await renderReview();
    const input = screen.getByRole("textbox", { name: "你的预测" });
    fireEvent.change(input, { target: { value: "old response" } });
    api.fetchReviewSession.mockResolvedValue(sessionFor({ ...knowledgeExercise(), exercise_version_id: "exercise-review-v2" }));
    fireEvent.click(screen.getByRole("button", { name: "渐进提示" }));
    await waitFor(() => expect(api.requestReviewHint).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "你的预测" })).toHaveValue(""));
    expect(screen.getByRole("button", { name: "提交复习答案" })).toBeDisabled();
    expect(api.createReviewAttempt).not.toHaveBeenCalled();
  });

  it("keeps raw HTML inert in the existing SafeMarkdown renderer", async () => {
    const exercise = knowledgeExercise();
    exercise.learner_prompt.prompt_markdown = '<script>alert("unsafe")</script>\n\n**Public question**';
    await renderReview(exercise);
    expect(screen.getByText("Public question")).toBeInTheDocument();
    expect(document.querySelector(".review-exercise script")).toBeNull();
  });

  it("preserves the structured model-code-review submission path", async () => {
    const exercise: ReviewExercise = {
      ...knowledgeExercise(), exercise_type: "model_code_review",
      learner_prompt: { schema_version: "model_code_review_prompt_v1", requirements: ["Inspect the code"], review_scope: ["correctness"], evidence_boundary: "prepublication_verified", learner_instruction: "Review this code" },
      starter_artifact: { schema_version: "model_code_review_artifact_v1", language_id: "python", runtime_label: "Python", model_code: "print(1)", code_hash: "d".repeat(64), line_count: 1 },
    };
    api.fetchReviewSession.mockResolvedValue(sessionFor(exercise));
    render(<ReviewSessionPanel userId="user-review" track={track} queue={queue} initialSessionId="session-review" onContextReference={vi.fn()} />);
    await screen.findByText("Review this code");
    expect(screen.queryByText(/公开回答格式暂不受支持/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "提交复习答案" }));
    await waitFor(() => expect(api.createReviewAttempt).toHaveBeenCalledTimes(1));
    expect(api.createReviewAttempt).toHaveBeenCalledWith(expect.objectContaining({
      reviewSubmission: { schema_version: "model_code_review_submission_v1", verdict: "uncertain", findings: [], supplemental_note: null },
      expectedSessionVersion: 7, expectedItemVersion: 4,
    }));
    expect(api.createReviewAttempt.mock.calls[0][0]).not.toHaveProperty("submission");
    await waitFor(() => expect(screen.getByRole("button", { name: "提交复习答案" })).toBeEnabled());
  });
});
