import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { TutorBranchResponseDisposition, TutorPublicBranchGroup, TutorPublicBranchGroupV1, TutorPublicBranchGroupV2 } from "../../../types";
import { ClarificationBranchGroup } from "./ClarificationBranchGroup";
import { readBranchExpanded, resetArtifactUiStateCachesForTests, writeBranchExpanded } from "./artifactUiState";

const notice = "教学会话已更新，此答疑分支已退役";
function legacyGroup(state: "active" | "resolved" = "active"): TutorPublicBranchGroupV1 {
  return {
    schema_version: "tutor_conversation_branch_v1", branch_id: "branch-history", anchor_artifact_id: "artifact-history",
    teaching_session_id: "session-history", checkpoint_id: "checkpoint-history", state,
    disposition: state === "resolved" ? "answer_and_refocus" : null, round_count: 1, item_count: 1,
    collapsed: state === "resolved",
    items: [{ item_sequence: 1, branch_round: 1, item_kind: "message", item_id: "learner-history", turn_id: "turn-history", item_role: "learner" }],
    created_at: "2026-09-13T07:00:00Z", resolved_at: state === "resolved" ? "2026-09-13T07:00:01Z" : null,
  };
}
function supersededGroup(disposition: TutorBranchResponseDisposition | null = null): TutorPublicBranchGroupV2 {
  return { ...legacyGroup(), schema_version: "tutor_conversation_branch_v2", state: "superseded", disposition,
    collapsed: true, resolved_at: null, superseded_at: "2026-09-13T07:00:02Z" };
}
function history(branch: TutorPublicBranchGroup, conversationId = "conversation-history") {
  return <ClarificationBranchGroup conversationId={conversationId} branch={branch}>
    <p>尚未得到回答的历史问题</p>
  </ClarificationBranchGroup>;
}
const toggle = () => screen.getByRole("button", { name: "答疑 · 1 轮" });

beforeEach(() => resetArtifactUiStateCachesForTests());

describe("ClarificationBranchGroup supersession", () => {
  it.each<TutorBranchResponseDisposition | null>([null, "answer_and_refocus", "offer_switch", "confirmed_switch"])("shows collapsed read-only retirement for disposition %s, not a resolution or switch action", (disposition) => {
    const { container } = render(history(supersededGroup(disposition)));
    expect(screen.getByRole("status")).toHaveTextContent(notice);
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    expect(toggle()).toHaveAccessibleDescription(notice);
    expect(screen.queryByText("尚未得到回答的历史问题")).not.toBeInTheDocument();
    expect(screen.queryByText(/已解决|答疑进行中/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /继续|切换|提交|重试/ })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(container.querySelector(".tutor-clarification-branch.superseded")).toHaveAttribute("data-anchor-artifact-id", "artifact-history");
  });

  it("allows keyboard expansion and collapse of retired history without a write action", async () => {
    const user = userEvent.setup();
    render(history(supersededGroup()));
    await user.tab();
    expect(toggle()).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(toggle()).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("尚未得到回答的历史问题")).toBeInTheDocument();
    expect(document.getElementById(toggle().getAttribute("aria-controls") ?? "")).not.toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent(notice);
    expect(screen.getAllByRole("button")).toHaveLength(1);
    await user.keyboard(" ");
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("尚未得到回答的历史问题")).not.toBeInTheDocument();
  });

  it("collapses an active branch once on supersession and preserves a manual reopen on refresh", () => {
    const view = render(history(legacyGroup()));
    expect(screen.getByRole("status")).toHaveTextContent("答疑进行中");
    expect(screen.getByText("尚未得到回答的历史问题")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    const retired = supersededGroup();
    view.rerender(history(retired));
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("尚未得到回答的历史问题")).not.toBeInTheDocument();
    fireEvent.click(toggle());
    expect(screen.getByText("尚未得到回答的历史问题")).toBeInTheDocument();
    view.rerender(history(structuredClone(retired)));
    expect(toggle()).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("尚未得到回答的历史问题")).toBeInTheDocument();
  });

  it("resets an expanded resolved cache entry when its server state becomes superseded", () => {
    const view = render(history(legacyGroup("resolved")));
    fireEvent.click(toggle());
    expect(toggle()).toHaveAttribute("aria-expanded", "true");
    view.rerender(history(supersededGroup("answer_and_refocus")));
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("status")).toHaveTextContent(notice);
    fireEvent.click(toggle());
    view.rerender(history(supersededGroup("answer_and_refocus")));
    expect(toggle()).toHaveAttribute("aria-expanded", "true");
  });

  it("retains manual expansion across remounts while isolating conversations", () => {
    const branch = supersededGroup();
    const first = render(history(branch));
    fireEvent.click(toggle());
    first.unmount();
    const other = render(history(branch, "another-conversation"));
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    other.unmount();
    render(history(structuredClone(branch)));
    expect(toggle()).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("尚未得到回答的历史问题")).toBeInTheDocument();
  });

  it("keeps the V1 active-to-resolved presentation and cache rules", () => {
    const active = legacyGroup();
    expect(readBranchExpanded("conversation-history", active)).toBe(true);
    writeBranchExpanded("conversation-history", active, false);
    expect(readBranchExpanded("conversation-history", active)).toBe(true);
    const view = render(history(active));
    view.rerender(history(legacyGroup("resolved")));
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(notice)).not.toBeInTheDocument();
    fireEvent.click(toggle());
    view.rerender(history(legacyGroup("resolved")));
    expect(toggle()).toHaveAttribute("aria-expanded", "true");
    expect(screen.queryByText(notice)).not.toBeInTheDocument();
  });
});
