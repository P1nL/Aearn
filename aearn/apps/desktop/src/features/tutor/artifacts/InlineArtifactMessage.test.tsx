import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";

import type { TutorArtifactPresentation, TutorPublicArtifactItem } from "../../../types";
import { ARTIFACT_PRESENTATION_TYPES, artifactRendererFor } from "./ArtifactRendererRegistry";
import { InlineArtifactMessage } from "./InlineArtifactMessage";
import { readArtifactUiState, resetArtifactUiStateCachesForTests, writeArtifactUiState } from "./artifactUiState";

const scrollIntoView = vi.fn();

function artifact(presentation: TutorArtifactPresentation, update: Partial<TutorPublicArtifactItem> = {}): TutorPublicArtifactItem {
  return {
    kind: "artifact",
    id: "artifact-1",
    conversation_id: "conversation-1",
    turn_id: "turn-artifact",
    learning_track_id: "track-1",
    knowledge_key: "javascript.dom",
    teaching_session_id: "session-1",
    checkpoint_id: "checkpoint-1",
    artifact_version: 1,
    artifact_kind: "knowledge_check",
    purpose: "knowledge_check",
    owner_kind: "teaching_practice",
    owner_id: "owner-1",
    owner_version: 1,
    state: "active",
    blocking: true,
    title: "对话内工件",
    instruction_markdown: "请阅读 **任务说明**。",
    difficulty: "D3",
    presentation,
    allowed_actions: ["respond"],
    source_references: [],
    active_attempt: null,
    branch_summary: null,
    version: 1,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
    terminal_at: null,
    ...update,
  };
}

const presentations: TutorArtifactPresentation[] = [
  { type: "exercise_workspace_v1", exercise_version_id: "exercise-1", language_id: "typescript", editor_mode: "code", starter_content: "const value = 1;", starter_content_hash: "a".repeat(64), editable: true, live_preview: true, runtime_profile_key: "node.typescript" },
  { type: "browser_preview_v1", source_artifact_id: "artifact-source", source_content_hash: "b".repeat(64), experience_tier: "local_non_authoritative", interactive: true },
  { type: "test_result_v1", attempt_id: "attempt-1", status: "pending", outcome: null, passed_count: 0, total_count: 2, summary_markdown: "", result_hash: null },
  { type: "knowledge_check_v1", response_kind: "single_select", prompt_markdown: "**选择**正确答案。", options: [{ value: "a", label: "A" }], minimum_selections: 1, maximum_selections: 1, maximum_text_length: 200 },
  { type: "model_code_review_v1", exercise_version_id: "exercise-1", language_id: "typescript", source_code: "const value = 1;", source_code_hash: "c".repeat(64), line_count: 1, review_categories: ["logic"] },
  { type: "sql_workspace_v1", exercise_version_id: "exercise-1", dialect: "sqlite", starter_query: "select 1", starter_query_hash: "d".repeat(64), schema_markdown: "users(id)", max_rows: 100 },
  { type: "demonstration_v1", demonstration_mode: "static", language_id: "html", source_content: "<button>Demo</button>", source_content_hash: "e".repeat(64), expected_event_key: null, duration_seconds: 10 },
  { type: "source_inspector_v1", document_id: "document-1", document_content_hash: "f".repeat(64), block_id: "block-1", excerpt: "稳定来源摘录", citation_ids: ["citation-1"] },
];

describe("InlineArtifactMessage", () => {
  beforeEach(() => {
    resetArtifactUiStateCachesForTests();
    scrollIntoView.mockReset();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scrollIntoView });
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  });

  it("registers every current presentation discriminator through a static renderer", () => {
    expect(ARTIFACT_PRESENTATION_TYPES).toEqual([
      "exercise_workspace_v1",
      "browser_preview_v1",
      "test_result_v1",
      "knowledge_check_v1",
      "model_code_review_v1",
      "model_code_review_v2",
      "sql_workspace_v1",
      "demonstration_v1",
      "demonstration_v2",
      "source_inspector_v1",
    ]);
    for (const presentation of presentations) expect(artifactRendererFor(presentation.type)).not.toBeNull();
  });

  it.each(presentations.map((presentation) => [presentation.type, presentation] as const))("renders known presentation %s without a contract error", (_type, presentation) => {
    const { container } = render(<InlineArtifactMessage artifact={artifact(presentation)} />);
    expect(container.querySelector('[data-artifact-id="artifact-1"]')).toHaveAttribute("data-presentation", presentation.type);
    expect(screen.getByText("任务说明")).toHaveTextContent("任务说明");
    expect(screen.getByText("D(3)")).toBeInTheDocument();
    expect(screen.queryByText("ARTIFACT_PRESENTATION_CONTRACT_ERROR")).not.toBeInTheDocument();
  });
  it("uses concise learner-facing region labels for every registered placeholder", () => {
    const labels = ["代码练习", "浏览器预览", "测试结果", "结构化检查", "代码审查", "SQL 工作区", "教学演示", "来源定位"];
    const rendered = render(<>{presentations.map((presentation, index) => <InlineArtifactMessage
      key={presentation.type}
      artifact={artifact(presentation, { id: `artifact-${index + 1}` })}
    />)}</>);

    for (const label of labels) expect(screen.getByRole("region", { name: label })).toBeInTheDocument();
    for (const label of labels) expect(screen.queryByRole("region", { name: `${label}组件接缝` })).not.toBeInTheDocument();
    expect(rendered.container).not.toHaveTextContent("组件接缝");
  });

  it("fails an unknown presentation closed and never projects its actions or arbitrary content", () => {
    const unknown = artifact({ type: "unknown_widget_v1", html: "<script>boom</script>" } as unknown as TutorArtifactPresentation);
    const { container } = render(<InlineArtifactMessage artifact={unknown} onAction={vi.fn()} />);

    expect(screen.getByRole("alert")).toHaveTextContent("ARTIFACT_PRESENTATION_CONTRACT_ERROR");
    expect(screen.queryByRole("button", { name: "作答" })).not.toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
    expect(container).not.toHaveTextContent("boom");
  });

  it("projects server allowed_actions through the typed callback without inventing result authority", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    const item = artifact(presentations[3], { allowed_actions: ["request_hint", "respond", "cancel"] });
    render(<InlineArtifactMessage artifact={item} onAction={onAction} />);

    await user.click(screen.getByRole("radio", { name: "A" }));
    await user.click(screen.getByRole("button", { name: "提交回答" }));
    expect(onAction).toHaveBeenCalledWith({
      artifact: item,
      action: "respond",
      payload: { action: "respond", response: { kind: "single_select", value: "a" } },
    });
    expect(screen.queryByText(/score|pass|Attempt/i)).not.toBeInTheDocument();
  });

  it("preserves expansion and future component/model/scroll/tab seams across artifact versions", async () => {
    const user = userEvent.setup();
    const first = artifact(presentations[0]);
    const rendered = render(<InlineArtifactMessage artifact={first} />);
    const toggle = rendered.container.querySelector(".inline-artifact-toggle") as HTMLButtonElement;
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    writeArtifactUiState(first, { component: { editorView: "ready" }, model: "model-1", scrollTop: 84, tab: "preview" });

    const second = { ...first, version: 2, updated_at: "2026-09-01T00:00:01Z" };
    rendered.rerender(<InlineArtifactMessage artifact={second} />);
    await waitFor(() => expect(toggle).toHaveAttribute("aria-expanded", "false"));
    expect(readArtifactUiState(second, true)).toMatchObject({
      expanded: false,
      component: { editorView: "ready" },
      model: "model-1",
      scrollTop: 84,
      tab: "preview",
    });
  });

  it("keeps a newly terminal artifact expanded until the next mainline learner marker, then respects manual reopen", async () => {
    const user = userEvent.setup();
    const active = artifact(presentations[2], { allowed_actions: ["run"] });
    const rendered = render(<InlineArtifactMessage artifact={active} />);
    const toggle = rendered.container.querySelector(".inline-artifact-toggle") as HTMLButtonElement;
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    const completedPresentation: Extract<TutorArtifactPresentation, { type: "test_result_v1" }> = {
      type: "test_result_v1",
      attempt_id: "attempt-1",
      status: "terminal",
      outcome: "passed",
      passed_count: 2,
      total_count: 2,
      summary_markdown: "**测试完成**",
      result_hash: "9".repeat(64),
    };
    const completed = artifact(completedPresentation, { state: "completed", allowed_actions: [], version: 2, terminal_at: "2026-09-01T00:00:02Z" });
    rendered.rerender(<InlineArtifactMessage artifact={completed} />);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("测试完成")).toBeInTheDocument();

    rendered.rerender(<InlineArtifactMessage artifact={completed} terminalCollapseMarker="learner-mainline-2" />);
    await waitFor(() => expect(toggle).toHaveAttribute("aria-expanded", "false"));
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    rendered.rerender(<InlineArtifactMessage artifact={{ ...completed, updated_at: "2026-09-01T00:00:03Z" }} terminalCollapseMarker="learner-mainline-2" />);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  it("defaults an uncached terminal heavy body collapsed", () => {
    const completed = artifact(presentations[4], { state: "completed", allowed_actions: [], terminal_at: "2026-09-01T00:00:02Z" });
    const { container } = render(<InlineArtifactMessage artifact={completed} />);
    expect(container.querySelector(".inline-artifact-toggle")).toHaveAttribute("aria-expanded", "false");
    expect(container.querySelector(".inline-artifact-body")).toBeNull();
  });
  it("loads terminal heavy detail only on expansion and caches it by Artifact version", async () => {
    const user = userEvent.setup();
    const completed = artifact(presentations[4], { state: "completed", allowed_actions: [], terminal_at: "2026-09-01T00:00:02Z" });
    const loadDetail = vi.fn().mockResolvedValue(completed);
    const rendered = render(<InlineArtifactMessage artifact={completed} loadDetail={loadDetail} />);
    const toggle = rendered.container.querySelector(".inline-artifact-toggle") as HTMLButtonElement;

    expect(loadDetail).not.toHaveBeenCalled();
    await user.click(toggle);
    expect(await screen.findByRole("region", { name: "代码审查" })).toBeInTheDocument();
    expect(loadDetail).toHaveBeenCalledTimes(1);
    await user.click(toggle);
    await user.click(toggle);
    expect(await screen.findByRole("region", { name: "代码审查" })).toBeInTheDocument();
    expect(loadDetail).toHaveBeenCalledTimes(1);
  });

  it("scrolls only a newly revealed artifact without stealing focus and uses reduced motion behavior", async () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    const item = artifact(presentations[1]);
    const rendered = render(<div><input aria-label="保留焦点" /><InlineArtifactMessage artifact={item} /></div>);
    const input = screen.getByRole("textbox", { name: "保留焦点" });
    input.focus();
    expect(input).toHaveFocus();

    rendered.rerender(<div><input aria-label="保留焦点" /><InlineArtifactMessage artifact={item} autoReveal /></div>);
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(1));
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "auto", block: "start" });
    expect(input).toHaveFocus();

    rendered.rerender(<div><input aria-label="保留焦点" /><InlineArtifactMessage artifact={{ ...item, version: 2, state: "running" }} autoReveal /></div>);
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(input).toHaveFocus();
  });
  it("scrolls an auto-revealed artifact only once when StrictMode replays effects", async () => {
    const item = artifact(presentations[1]);
    const rendered = render(<StrictMode><InlineArtifactMessage artifact={item} autoReveal /></StrictMode>);

    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(1));
    rendered.rerender(<StrictMode><InlineArtifactMessage artifact={{ ...item, version: 2, state: "running" }} autoReveal /></StrictMode>);
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
  });
});
