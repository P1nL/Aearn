import { useEffect, useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  createOrResumeTutorConversation: vi.fn(),
  fetchLearningRoadmap: vi.fn(),
  fetchLearningTrackDetail: vi.fn(),
  fetchReviewQueue: vi.fn(),
  fetchTeachingSessions: vi.fn(),
  openTeachingSession: vi.fn(),
  mutateTeachingSession: vi.fn(),
}));
const mounts = vi.hoisted(() => ({ tutor: 0, lesson: 0 }));
vi.mock("../../../api", () => api);
vi.mock("../../tutor/TutorConversationSurface", () => ({
  TutorConversationSurface: ({ onOpenDocumentReference }: { onOpenDocumentReference?: (request: unknown, trigger: HTMLElement) => void }) => {
    const [draft, setDraft] = useState("");
    useEffect(() => { mounts.tutor += 1; }, []);
    return <div><label>Tutor 草稿<input aria-label="Tutor 草稿" value={draft} onChange={(event) => setDraft(event.target.value)} /></label><button type="button" onClick={(event) => onOpenDocumentReference?.({ knowledgeKey: "javascript.closure", source: { kind: "context_reference", reference_id: "88888888-8888-4888-8888-888888888888" } }, event.currentTarget)}>Tutor 来源</button></div>;
  },
}));
vi.mock("../LessonDocumentPage", () => ({
  LessonDocumentPage: ({ onAuthorityChange, onOpenDocumentReference }: { onAuthorityChange?: (state: unknown) => void; onOpenDocumentReference?: (request: unknown, trigger: HTMLElement) => void }) => {
    const [selection, setSelection] = useState("");
    useEffect(() => { mounts.lesson += 1; }, []);
    useEffect(() => { onAuthorityChange?.(lessonState); }, [onAuthorityChange]);
    return <div><label>Lesson 选择<input aria-label="Lesson 选择" value={selection} onChange={(event) => setSelection(event.target.value)} /></label><button type="button" onClick={(event) => onOpenDocumentReference?.({ knowledgeKey: "javascript.closure", source: { kind: "lesson_block", document_id: lessonState.assignment.document_id, document_content_hash: lessonState.document.content_hash, assignment_version: 2, block_id: "concept", citation_id: null } }, event.currentTarget)}>Lesson 来源</button></div>;
  },
}));
vi.mock("../lesson/LessonDocumentDrawer", () => ({
  LessonDocumentDrawer: ({ request, onClose }: { request: { source: { kind: string } }; onClose: () => void }) => <aside role="dialog" aria-label="来源文档测试抽屉"><span>{request.source.kind}</span><button type="button" onClick={onClose}>关闭来源文档</button></aside>,
}));
vi.mock("../LearningRoadmapPanel", () => ({ LearningRoadmapPanel: () => <div>Roadmap</div> }));
vi.mock("../ReviewSessionPanel", () => ({ ReviewSessionPanel: () => <div>Review</div> }));

import { TrackLearningWorkspace } from "../TrackLearningWorkspace";

const userProfile = {
  id: "11111111-1111-4111-8111-111111111111", display_name: "测试用户", learning_style: null, teaching_preference: null,
  encouragement_preference: null, profession: null, background_context: null, preferred_time_slots: [], reminder_preference: {},
  created_at: "2026-08-23T00:00:00Z", updated_at: "2026-08-23T00:00:00Z",
};
const track = {
  track_id: "22222222-2222-4222-8222-222222222222", language_id: "javascript", language_display_name: "JavaScript", goal_text: "掌握闭包", target_level: "intermediate",
  status: "active" as const, version: 3, active_revision_id: "revision-1", active_plan_title: "JavaScript 主线", current_knowledge_key: "javascript.closure", current_knowledge_title: "闭包",
  progress: { total: 3, completed: 0, in_progress: 1, review_due: 0, percent: 12 }, review_due_count: 0,
  execution_tier: "teaching_local" as const, execution_disclosure: "本地教学执行", last_learned_at: null, updated_at: null, created_at: null, archived_at: null,
};
const roadmap = { track_id: track.track_id, active_revision_id: "revision-1", title: "JavaScript 主线", target_level: "intermediate", modules: [{ module_id: "module-1", module_key: "basics", title: "基础", description: "", order_index: 0, is_core: true, is_skippable: false, nodes: [{ node_id: "node-1", knowledge_key: "javascript.closure", title: "闭包", description: "", order_index: 0, is_core: true, prerequisite_keys: [], required_capabilities: [], progress_status: "available" as const, progress_version: 2, mastery_level: "new", mastery_confidence: 0 }] }] };
const lessonState = {
  status: "ready" as const, track_id: track.track_id, module_key: "basics", module_diagnostic_allowed: false, knowledge_key: "javascript.closure", track_version: 3,
  progress_version: 2, progress_status: "available", assignment: { assignment_id: "44444444-4444-4444-8444-444444444444", document_id: "55555555-5555-4555-8555-555555555555", assignment_version: 2, status: "active" as const, content_hash: "a".repeat(64), started_at: null, activated_at: null, progress_status: "available", progress_version: 2 },
  document: { schema_version: "lesson_document_v1" as const, title: "闭包", language_id: "javascript", knowledge_key: "javascript.closure", content_standard_version: "v1", coverage_keys: ["javascript.closure"], blocks: [], content_hash: "a".repeat(64) },
  sources: [], update: null, authoring_run: null,
};
function session(mode: "guided" | "free_reading", version: number) {
  return {
    session_id: "66666666-6666-4666-8666-666666666666", track_id: track.track_id, track_version: 3,
    conversation_id: "33333333-3333-4333-8333-333333333333", knowledge_key: "javascript.closure", status: "active" as const, mode,
    session_version: version, progress_version: 2, assignment_id: lessonState.assignment.assignment_id, assignment_version: 2,
    document_id: lessonState.assignment.document_id, checkpoint_id: "77777777-7777-4777-8777-777777777777", paused_at: null, completed_at: null, last_activity_at: null,
    checkpoint: { checkpoint_id: "77777777-7777-4777-8777-777777777777", session_version: version, objective: { objective_id: "knowledge:javascript.closure", summary: "闭包", source_handles: ["knowledge:javascript.closure"] }, active_focus: null, suspended_focuses: [], unresolved_questions: [], covered_concepts: [], evidence_cursors: [], pause_reason: "soft_pause" as const, recommended_action_key: "continue" },
    action_shelf: { schema_version: "teaching_action_shelf_v1" as const, teaching_session_id: "66666666-6666-4666-8666-666666666666", session_version: version, checkpoint_id: "77777777-7777-4777-8777-777777777777", state: mode === "guided" ? "ready" as const : "free_reading" as const, primary_action: null, secondary_actions: [], overflow_actions: [] },
    allowed_actions: [],
  };
}

describe("TrackLearningWorkspace teaching role swap", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mounts.tutor = 0; mounts.lesson = 0;
    api.fetchLearningTrackDetail.mockResolvedValue(track);
    api.fetchLearningRoadmap.mockResolvedValue(roadmap);
    api.fetchReviewQueue.mockResolvedValue({ track_id: track.track_id, as_of: null, due_count: 0, items: [], critical_prerequisite_gate: null });
    api.createOrResumeTutorConversation.mockResolvedValue({ conversation_id: "33333333-3333-4333-8333-333333333333", created: false, idempotent_replayed: false });
    api.openTeachingSession.mockResolvedValue({ teaching_session: session("guided", 1), created: false, pending_run: null, idempotent_replayed: false });
    api.fetchTeachingSessions.mockResolvedValue({ items: [session("guided", 1)] });
    api.mutateTeachingSession.mockResolvedValue({ teaching_session: session("free_reading", 2), pending_run: null, idempotent_replayed: false });
  });

  it("does not reopen failed authority on rerenders; explicit refresh retries once", async () => {
    const user = userEvent.setup();
    api.openTeachingSession.mockRejectedValue(new Error("authority conflict"));
    const rendered = render(<TrackLearningWorkspace user={userProfile} trackId={track.track_id} onBack={vi.fn()} />);
    const retry = await screen.findByRole("button", { name: "刷新 authority" });
    expect(api.openTeachingSession).toHaveBeenCalledTimes(1);
    rendered.rerender(<TrackLearningWorkspace user={userProfile} trackId={track.track_id} onBack={vi.fn()} />);
    await user.type(screen.getByRole("textbox", { name: "Tutor 草稿" }), "keep draft");
    expect(api.openTeachingSession).toHaveBeenCalledTimes(1);
    await user.click(retry);
    await waitFor(() => expect(api.openTeachingSession).toHaveBeenCalledTimes(2));
  });

  it("swaps CSS roles without remounting Tutor or Lesson state", async () => {
    const user = userEvent.setup();
    const rendered = render(<TrackLearningWorkspace user={userProfile} trackId={track.track_id} onBack={vi.fn()} />);

    const switcher = await screen.findByRole("button", { name: "切换到自由阅读，课程成为主区域" });
    expect(switcher).toHaveTextContent("⇄");
    expect(switcher).not.toHaveTextContent("自由阅读");
    const tutorDraft = screen.getByRole("textbox", { name: "Tutor 草稿" });
    const lessonSelection = screen.getByRole("textbox", { name: "Lesson 选择" });
    await user.type(tutorDraft, "不要丢失");
    await user.type(lessonSelection, "选区状态");
    expect(rendered.container.querySelector(".learning-workspace-grid")).toHaveClass("teaching-guided");

    await user.click(switcher);
    await waitFor(() => expect(api.mutateTeachingSession).toHaveBeenCalledWith(expect.objectContaining({ controlKey: "switch_mode", targetMode: "free_reading" })));
    await waitFor(() => expect(rendered.container.querySelector(".learning-workspace-grid")).toHaveClass("teaching-free_reading"));
    expect(screen.getByRole("textbox", { name: "Tutor 草稿" })).toHaveValue("不要丢失");
    expect(screen.getByRole("textbox", { name: "Lesson 选择" })).toHaveValue("选区状态");
    expect(mounts.tutor).toBe(1);
    expect(mounts.lesson).toBe(1);
  });

  it("independently collapses and restores both desktop side panels", async () => {
    const user = userEvent.setup();
    const rendered = render(<TrackLearningWorkspace user={userProfile} trackId={track.track_id} onBack={vi.fn()} />);
    const collapseRoadmap = await screen.findByRole("button", { name: "收起左侧学习路线" });
    const grid = rendered.container.querySelector<HTMLElement>(".learning-workspace-grid")!;

    await user.click(collapseRoadmap);
    expect(grid).toHaveClass("roadmap-collapsed");
    expect(screen.getByRole("button", { name: "展开左侧学习路线" })).toHaveAttribute("aria-expanded", "false");

    await user.click(screen.getByRole("button", { name: "收起右侧辅助面板" }));
    expect(grid).toHaveClass("secondary-collapsed");
    expect(screen.getByRole("button", { name: "展开右侧辅助面板" })).toHaveAttribute("aria-expanded", "false");

    await user.click(screen.getByRole("button", { name: "展开左侧学习路线" }));
    await user.click(screen.getByRole("button", { name: "展开右侧辅助面板" }));
    expect(grid).not.toHaveClass("roadmap-collapsed");
    expect(grid).not.toHaveClass("secondary-collapsed");
    expect(mounts.tutor).toBe(1);
    expect(mounts.lesson).toBe(1);
  });

  it("opens and closes the source drawer without remounting Tutor or Lesson and restores the exact trigger focus", async () => {
    const user = userEvent.setup();
    render(<TrackLearningWorkspace user={userProfile} trackId={track.track_id} onBack={vi.fn()} />);

    const tutorDraft = await screen.findByRole("textbox", { name: "Tutor 草稿" });
    const lessonSelection = screen.getByRole("textbox", { name: "Lesson 选择" });
    await user.type(tutorDraft, "保留工件编辑状态");
    await user.type(lessonSelection, "保留课程选区");
    const trigger = screen.getByRole("button", { name: "Tutor 来源" });
    await user.click(trigger);

    expect(screen.getByRole("dialog", { name: "来源文档测试抽屉" })).toHaveTextContent("context_reference");
    expect(screen.getByRole("textbox", { name: "Tutor 草稿" })).toHaveValue("保留工件编辑状态");
    expect(screen.getByRole("textbox", { name: "Lesson 选择" })).toHaveValue("保留课程选区");
    expect(mounts.tutor).toBe(1);
    expect(mounts.lesson).toBe(1);

    await user.click(screen.getByRole("button", { name: "关闭来源文档" }));
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(screen.queryByRole("dialog", { name: "来源文档测试抽屉" })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Tutor 草稿" })).toHaveValue("保留工件编辑状态");
    expect(screen.getByRole("textbox", { name: "Lesson 选择" })).toHaveValue("保留课程选区");
    expect(mounts.tutor).toBe(1);
    expect(mounts.lesson).toBe(1);
  });
});
