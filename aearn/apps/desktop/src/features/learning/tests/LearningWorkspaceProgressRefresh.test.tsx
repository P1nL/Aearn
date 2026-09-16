import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  createOrResumeTutorConversation: vi.fn(),
  fetchLearningRoadmap: vi.fn(),
  fetchLearningTrackDetail: vi.fn(),
  fetchReviewQueue: vi.fn(),
}));
vi.mock("../../../api", () => api);
vi.mock("../LessonDocumentPage", () => ({
  LessonDocumentPage: ({ onProgressChange }: { onProgressChange?: (attempt: { track_id: string; knowledge_key: string; status: "pending" | "terminal"; projected: boolean | null; route_changed: boolean }) => Promise<void> | void }) => (
    <div>
      <button type="button" onClick={() => void onProgressChange?.(passedAttempt)}>模拟服务端通过</button>
      <button type="button" onClick={() => void onProgressChange?.(failedAttempt)}>模拟服务端失败</button>
    </div>
  ),
}));
vi.mock("../LearningRoadmapPanel", () => ({
  LearningRoadmapPanel: ({ roadmap, selectedKnowledgeKey }: { roadmap: typeof initialRoadmap; selectedKnowledgeKey: string | null }) => (
    <div>
      <span data-testid="selected-knowledge-key">{selectedKnowledgeKey}</span>
      <span data-testid="route-node-status">{roadmap.modules[0]?.nodes[0]?.progress_status}</span>
    </div>
  ),
}));
vi.mock("../ReviewSessionPanel", () => ({ ReviewSessionPanel: () => <div>Review</div> }));
vi.mock("../../tutor/TutorConversationSurface", () => ({ TutorConversationSurface: () => <div>Tutor</div> }));
vi.mock("../lesson/LessonDocumentDrawer", () => ({ LessonDocumentDrawer: () => null }));

import { TrackLearningWorkspace } from "../TrackLearningWorkspace";

const trackId = "22222222-2222-4222-8222-222222222222";
const user = {
  id: "11111111-1111-4111-8111-111111111111",
  display_name: "测试用户",
  learning_style: null,
  teaching_preference: null,
  encouragement_preference: null,
  profession: null,
  background_context: null,
  preferred_time_slots: [],
  reminder_preference: {},
  created_at: "2026-08-23T00:00:00Z",
  updated_at: "2026-08-23T00:00:00Z",
};
const initialTrack = {
  track_id: trackId,
  language_id: "python",
  language_display_name: "Python",
  goal_text: "掌握基础",
  target_level: "beginner",
  status: "active",
  version: 3,
  active_revision_id: "revision-1",
  active_plan_title: "Python 主线",
  current_knowledge_key: "n1_1",
  current_knowledge_title: "变量",
  progress: { total: 12, completed: 0, in_progress: 1, review_due: 0, percent: 0 },
  review_due_count: 0,
  execution_tier: "teaching_local",
  execution_disclosure: "本地教学执行",
  last_learned_at: null,
  updated_at: null,
  created_at: null,
  archived_at: null,
};
const refreshedTrack = { ...initialTrack, version: 4, current_knowledge_key: "n1_2", current_knowledge_title: "条件分支", progress: { ...initialTrack.progress, completed: 1, in_progress: 1, percent: 8 } };
const initialRoadmap = {
  track_id: trackId,
  active_revision_id: "revision-1",
  title: "Python 主线",
  target_level: "beginner",
  modules: [{ module_id: "module-1", module_key: "basics", title: "基础", description: "", order_index: 0, is_core: true, is_skippable: false, nodes: [
    { node_id: "node-1", knowledge_key: "n1_1", title: "变量", description: "", order_index: 0, is_core: true, prerequisite_keys: [], required_capabilities: [], progress_status: "in_progress", progress_version: 3, mastery_level: "learning", mastery_confidence: 0.4 },
    { node_id: "node-2", knowledge_key: "n1_2", title: "条件分支", description: "", order_index: 1, is_core: true, prerequisite_keys: ["n1_1"], required_capabilities: [], progress_status: "locked", progress_version: 1, mastery_level: "new", mastery_confidence: 0 },
  ] }],
};
const refreshedRoadmap = { ...initialRoadmap, modules: [{ ...initialRoadmap.modules[0], nodes: [
  { ...initialRoadmap.modules[0].nodes[0], progress_status: "completed", progress_version: 4, mastery_level: "mastered", mastery_confidence: 1 },
  { ...initialRoadmap.modules[0].nodes[1], progress_status: "available", progress_version: 2 },
] }] };
const initialQueue = { track_id: trackId, as_of: null, due_count: 0, items: [], critical_prerequisite_gate: null };
const passedAttempt = { track_id: trackId, knowledge_key: "n1_1", status: "terminal" as const, projected: true, route_changed: true };
const failedAttempt = { track_id: trackId, knowledge_key: "n1_1", status: "terminal" as const, projected: false, route_changed: false };

beforeEach(() => {
  vi.clearAllMocks();
  api.createOrResumeTutorConversation.mockResolvedValue({ conversation_id: "33333333-3333-4333-8333-333333333333", created: false, idempotent_replayed: false });
  api.fetchLearningTrackDetail.mockResolvedValueOnce(initialTrack).mockResolvedValueOnce(refreshedTrack);
  api.fetchLearningRoadmap.mockResolvedValueOnce(initialRoadmap).mockResolvedValueOnce(refreshedRoadmap);
  api.fetchReviewQueue.mockResolvedValueOnce(initialQueue).mockResolvedValueOnce(initialQueue);
});

describe("TrackLearningWorkspace server-authoritative progress refresh", () => {
  it("refetches route summary after a projected terminal Attempt and keeps the completed lesson selected", async () => {
    const learner = userEvent.setup();
    render(<TrackLearningWorkspace user={user} trackId={trackId} onBack={vi.fn()} />);

    expect(await screen.findByTestId("selected-knowledge-key")).toHaveTextContent("n1_1");
    await learner.click(screen.getByRole("button", { name: "模拟服务端通过" }));

    await waitFor(() => {
      expect(api.fetchLearningTrackDetail).toHaveBeenCalledTimes(2);
      expect(api.fetchLearningRoadmap).toHaveBeenCalledTimes(2);
      expect(api.fetchReviewQueue).toHaveBeenCalledTimes(2);
    });
    expect(screen.getByText("8%")).toBeInTheDocument();
    expect(screen.getByTestId("route-node-status")).toHaveTextContent("completed");
    expect(screen.getByTestId("selected-knowledge-key")).toHaveTextContent("n1_1");
  });

  it("does not optimistically advance the route for a failed terminal Attempt", async () => {
    const learner = userEvent.setup();
    render(<TrackLearningWorkspace user={user} trackId={trackId} onBack={vi.fn()} />);

    await learner.click(await screen.findByRole("button", { name: "模拟服务端失败" }));
    expect(api.fetchLearningTrackDetail).toHaveBeenCalledTimes(1);
    expect(api.fetchLearningRoadmap).toHaveBeenCalledTimes(1);
    expect(api.fetchReviewQueue).toHaveBeenCalledTimes(1);
    expect(screen.getByText("0%")).toBeInTheDocument();
    expect(screen.getByTestId("route-node-status")).toHaveTextContent("in_progress");
  });
});
