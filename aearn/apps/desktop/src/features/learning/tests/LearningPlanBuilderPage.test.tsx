import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LearningPlanSession, UserProfile } from "../../../types";

const api = vi.hoisted(() => ({
  cancelLearningPlanSession: vi.fn(),
  confirmLearningPlanSession: vi.fn(),
  fetchLearningPlanSession: vi.fn(),
}));

vi.mock("../../../api", () => api);
vi.mock("../../tutor/TutorConversationSurface", () => ({
  TutorConversationSurface: ({ planningComposerPlaceholder }: { planningComposerPlaceholder?: string }) => (
    <textarea aria-label="计划 Composer" placeholder={planningComposerPlaceholder} />
  ),
}));

import { LearningPlanBuilderPage } from "../LearningPlanBuilderPage";

const user: UserProfile = {
  id: "user-1",
  display_name: "测试用户",
  learning_style: null,
  teaching_preference: null,
  encouragement_preference: null,
  profession: null,
  background_context: null,
  preferred_time_slots: [],
  reminder_preference: {},
  created_at: "2026-08-16T00:00:00Z",
  updated_at: "2026-08-16T00:00:00Z",
};

const session: LearningPlanSession = {
  session_id: "session-1",
  conversation_id: "conversation-1",
  status: "draft_ready",
  preferred_language_id: "html-css",
  version: 7,
  current_draft: {
    draft_id: "draft-2",
    draft_version: 2,
    content_hash: "a".repeat(64),
    profile: {
      language_id: "html-css",
      goal_text: "完成一个响应式作品集",
      target_level: "beginner",
      weekly_minutes: 300,
      experience_level: "beginner",
      teaching_preferences: [],
      pace_summary: "每周五次，每次一小时",
      title: "HTML/CSS 作品集入门计划",
    },
    plan: {
      title: "HTML/CSS 作品集入门计划",
      target_level: "beginner",
      modules: [{
        module_key: "html_structure",
        title: "HTML 结构",
        description: "建立语义化页面结构",
        order_index: 0,
        is_core: true,
        is_skippable: false,
        nodes: [{
          knowledge_key: "semantic_html",
          title: "语义化 HTML",
          description: "使用语义元素组织页面",
          order_index: 0,
          is_core: true,
          prerequisite_keys: [],
          required_capabilities: [],
        }],
      }],
    },
    sources: [{ source_id: "mdn-html", display_name: "MDN HTML", trust_tier: "official" }],
    generator_version: "learning-plan-draft-capability-v1",
    policy_version: "learning-plan-draft-policy-v1",
    created_at: "2026-08-16T00:00:00Z",
  },
  confirmed_track_id: null,
  last_error: null,
  created_at: "2026-08-16T00:00:00Z",
  updated_at: "2026-08-16T00:00:00Z",
  confirmed_at: null,
  cancelled_at: null,
};

describe("LearningPlanBuilderPage confirmation ownership", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.fetchLearningPlanSession.mockResolvedValue(session);
    api.confirmLearningPlanSession.mockResolvedValue({
      session: { ...session, status: "confirmed", confirmed_track_id: "track-1" },
      track: { track_id: "track-1" },
    });
  });

  it("keeps revision input in the Composer and confirms the exact draft only from the plan panel", async () => {
    const interaction = userEvent.setup();
    const onConfirmed = vi.fn();

    render(<LearningPlanBuilderPage user={user} initialSession={session} onBack={vi.fn()} onConfirmed={onConfirmed} />);

    expect(await screen.findByPlaceholderText("对计划有修改意见？直接告诉我……")).toBeInTheDocument();
    const confirmButtons = screen.getAllByRole("button", { name: "确认并创建学习主线" });
    expect(confirmButtons).toHaveLength(1);

    await interaction.click(confirmButtons[0]);

    await waitFor(() => expect(api.confirmLearningPlanSession).toHaveBeenCalledWith({
      userId: "user-1",
      session,
      clientActionId: expect.stringMatching(/^learning-plan-confirm:/),
    }));
    expect(onConfirmed).toHaveBeenCalledWith("track-1");
  });
});
