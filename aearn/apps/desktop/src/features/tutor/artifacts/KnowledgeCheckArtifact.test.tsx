import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TutorPublicArtifactItem } from "../../../types";
import { KnowledgeCheckArtifact } from "./KnowledgeCheckArtifact";

function artifact(update: Partial<TutorPublicArtifactItem> = {}): TutorPublicArtifactItem {
  return {
    kind: "artifact", id: "artifact-1", conversation_id: "conversation-1", turn_id: null,
    learning_track_id: "track-1", knowledge_key: "python.variables", teaching_session_id: "session-1",
    checkpoint_id: "checkpoint-1", artifact_version: 1, artifact_kind: "knowledge_check",
    purpose: "knowledge_check", owner_kind: "learning_item", owner_id: "item-1", owner_version: 1,
    state: "active", blocking: true, title: "变量检查", instruction_markdown: "请选择答案。", difficulty: "D2",
    presentation: {
      type: "knowledge_check_v1", response_kind: "single_select", prompt_markdown: "value 是多少？",
      options: [{ value: "2", label: "2" }, { value: "3", label: "3" }], minimum_selections: 1,
      maximum_selections: 1, maximum_text_length: 200,
      hints: [
        { level: 1, label: "方向", markdown: "看赋值右侧。" },
        { level: 2, label: "概念", markdown: "名称绑定到值。" },
      ],
      revealed_hint_levels: [1], answer_locked: false, outcome: null, assistance_kind: null,
      evaluation_markdown: "", response_receipt_id: null, remediation_handle: null, transfer_handle: null,
    },
    allowed_actions: ["request_hint", "respond"], source_references: [], active_attempt: null,
    branch_summary: null, version: 1, created_at: "2026-09-02T00:00:00Z", updated_at: "2026-09-02T00:00:00Z",
    terminal_at: null, ...update,
  };
}
function knowledgePresentation(): Extract<TutorPublicArtifactItem["presentation"], { type: "knowledge_check_v1" }> {
  const presentation = artifact().presentation;
  if (presentation.type !== "knowledge_check_v1") throw new Error("knowledge-check fixture mismatch");
  return presentation;
}


describe("KnowledgeCheckArtifact", () => {
  it("submits a structured response and keeps the original immutable", () => {
    const onAction = vi.fn();
    render(<KnowledgeCheckArtifact artifact={artifact()} onAction={onAction} />);
    fireEvent.click(screen.getByLabelText("2"));
    fireEvent.click(screen.getByRole("button", { name: "提交回答" }));
    expect(onAction).toHaveBeenCalledWith(expect.objectContaining({ payload: { action: "respond", response: { kind: "single_select", value: "2" } } }));
  });

  it("opens the overlay without reflow, pages manually, and closes on Escape", () => {
    render(<KnowledgeCheckArtifact artifact={artifact()} onAction={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "提示" }));
    const dialog = screen.getByRole("dialog", { name: "分级提示" });
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveClass("knowledge-check-hint-overlay");
    expect(dialog.closest("[data-testid=knowledge-check-hint-layer]")?.parentElement).toBe(document.body);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "分级提示" })).not.toBeInTheDocument();
  });

  it("unlocks each hint only through an explicit server action and never auto-advances", async () => {
    const onAction = vi.fn().mockResolvedValue(undefined);
    const hidden = artifact({
      presentation: {
        ...knowledgePresentation(),
        hints: [
          { level: 1, label: "方向", markdown: "看赋值右侧。" },
          { level: 2, label: "概念", markdown: "名称绑定到值。" },
        ],
        revealed_hint_levels: [],
      },
    });
    render(<KnowledgeCheckArtifact artifact={hidden} onAction={onAction} />);
    fireEvent.click(screen.getByRole("button", { name: "提示" }));
    expect(onAction).toHaveBeenCalledTimes(1);
    expect(onAction).toHaveBeenCalledWith(expect.objectContaining({
      action: "request_hint",
      payload: { action: "request_hint", hint_level: 1 },
    }));
  });

  it("supports manual keyboard paging and a separate direct-answer action", () => {
    const onAction = vi.fn();
    render(<KnowledgeCheckArtifact artifact={artifact({
      allowed_actions: ["request_hint", "request_direct_answer", "respond"],
      presentation: {
        ...knowledgePresentation(),
        revealed_hint_levels: [1, 2],
      },
    })} onAction={onAction} />);
    const trigger = screen.getByRole("button", { name: "提示" });
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "分级提示" });
    fireEvent.keyDown(dialog, { key: "ArrowRight" });
    expect(screen.getByText("2 / 2")).toBeInTheDocument();
    expect(onAction).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "关闭提示" }));
    fireEvent.click(screen.getByRole("button", { name: "查看答案" }));
    expect(onAction).toHaveBeenCalledWith(expect.objectContaining({
      action: "request_direct_answer",
      payload: { action: "request_direct_answer" },
    }));
  });

  it("opens a newly unlocked page and restores the original trigger focus", async () => {
    const initial = artifact();
    const updated = artifact({
      version: 2,
      presentation: {
        ...knowledgePresentation(),
        revealed_hint_levels: [1, 2],
      },
    });
    const onAction = vi.fn().mockResolvedValue(updated);
    const { rerender } = render(<KnowledgeCheckArtifact artifact={initial} onAction={onAction} />);
    const trigger = screen.getByRole("button", { name: "提示" });
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("button", { name: "查看 H2" }));
    await waitFor(() => expect(onAction).toHaveBeenCalledWith(expect.objectContaining({
      payload: { action: "request_hint", hint_level: 2 },
    })));
    rerender(<KnowledgeCheckArtifact artifact={updated} onAction={onAction} />);
    expect(await screen.findByText("H2 · 概念")).toBeInTheDocument();
    expect(document.querySelector('[aria-label="H1 方向"]')).toHaveAttribute("inert");
    fireEvent.keyDown(screen.getByRole("dialog", { name: "分级提示" }), { key: "Escape" });
    await waitFor(() => expect(trigger).toHaveFocus());
  });

});
