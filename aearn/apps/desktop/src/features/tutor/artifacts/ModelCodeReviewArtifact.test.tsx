import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@monaco-editor/react", () => ({
  default: ({ value }: { value: string }) => <pre data-testid="code-editor">{value}</pre>,
  DiffEditor: ({ original, modified }: { original: string; modified: string }) => <div data-testid="diff-editor"><pre>{original}</pre><pre>{modified}</pre></div>,
}));

import type { TutorPublicArtifactItem } from "../../../types";
import { ModelCodeReviewArtifact, mapModelReviewSelection } from "./ModelCodeReviewArtifact";

const HASH = "a".repeat(64);

function artifact(overrides: Partial<TutorPublicArtifactItem["presentation"]> = {}): TutorPublicArtifactItem {
  return {
    kind: "artifact",
    id: "artifact-review",
    conversation_id: "conversation-review",
    turn_id: "turn-review",
    learning_track_id: "track-review",
    knowledge_key: "python.variables",
    teaching_session_id: "session-review",
    checkpoint_id: "checkpoint-review",
    artifact_version: 1,
    artifact_kind: "model_code_review",
    purpose: "code_review",
    owner_kind: "learning_item",
    owner_id: "item-review",
    owner_version: 1,
    state: "active",
    blocking: true,
    title: "Review",
    instruction_markdown: "Find the verifiable issue.",
    difficulty: "D3",
    presentation: {
      type: "model_code_review_v2",
      exercise_version_id: "exercise-review",
      presentation_hash: HASH,
      review_target: {
        schema_version: "model_code_review_artifact_v2",
        presentation_mode: "code",
        language_id: "python",
        runtime_label: "Python 3",
        source_code: null,
        modified_code: "value = total / count",
        source_hash: null,
        modified_hash: HASH,
        diff_hash: HASH,
        line_count: 1,
        hunks: [{
          hunk_id: "code.h1",
          header: "@@ -1,1 +1,1 @@",
          source_start: 1,
          source_count: 1,
          modified_start: 1,
          modified_count: 1,
          lines: [{ line_key: "code.m1", kind: "context", text: "value = total / count", source_line: 1, modified_line: 1 }],
        }],
      },
      review_categories: ["requirements_drift", "fabricated_api", "logic_boundary", "contract_integration", "async_lifecycle", "security_trust", "error_false_success"],
      submission_locked: false,
      outcome: null,
      score: null,
      evaluation_markdown: "",
      review_receipt_id: null,
      result_hash: null,
      remediation_handle: null,
      ...overrides,
    } as TutorPublicArtifactItem["presentation"],
    allowed_actions: ["complete_review", "cancel"],
    source_references: [],
    active_attempt: null,
    branch_summary: null,
    version: 1,
    created_at: "2026-09-02T00:00:00+00:00",
    updated_at: "2026-09-02T00:00:00+00:00",
    terminal_at: null,
  };
}

describe("ModelCodeReviewArtifact", () => {
  it("submits one closed v2 finding payload owned by the renderer", async () => {
    const onAction = vi.fn().mockResolvedValue(undefined);
    render(<ModelCodeReviewArtifact artifact={artifact()} onAction={onAction} />);

    fireEvent.click(screen.getByRole("button", { name: "添加发现" }));
    expect(screen.queryByRole("option", { name: "弱测试（专题）" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("说明触发条件、违反的明确契约和可能影响。"), {
      target: { value: "count may be zero and division needs a guard" },
    });
    fireEvent.click(screen.getByRole("button", { name: "完成审查" }));

    await waitFor(() => expect(onAction).toHaveBeenCalledTimes(1));
    expect(onAction.mock.calls[0][0]).toMatchObject({
      action: "complete_review",
      payload: {
        action: "complete_review",
        review_submission: {
          schema_version: "model_code_review_submission_v2",
          presentation_hash: HASH,
          verdict: "correctness_issue",
          findings: [{
            hunk_id: "code.h1",
            side: "modified",
            start_line: 1,
            end_line: 1,
            category: "logic_boundary",
          }],
        },
      },
    });
  });

  it("keeps a terminal review read-only and renders only server feedback", () => {
    const terminal = artifact({
      submission_locked: true,
      outcome: "failed",
      score: 0.4,
      evaluation_markdown: "服务器已确定本次仍有遗漏。",
      review_receipt_id: "receipt-review",
      result_hash: "b".repeat(64),
      remediation_handle: `li:${"c".repeat(64)}`,
    });
    terminal.state = "completed";
    terminal.allowed_actions = [];
    terminal.terminal_at = "2026-09-02T00:01:00+00:00";

    render(<ModelCodeReviewArtifact artifact={terminal} />);

    expect(screen.queryByRole("button", { name: "完成审查" })).not.toBeInTheDocument();
    expect(screen.getByText("服务器已确定本次仍有遗漏。")).toBeInTheDocument();
    expect(screen.getByText("40%")).toBeInTheDocument();
  });

  it("renders a published diff target through the read-only DiffEditor", async () => {
    const diff = artifact();
    if (diff.presentation.type !== "model_code_review_v2") throw new Error("fixture mismatch");
    diff.presentation = {
      ...diff.presentation,
      review_target: {
        ...diff.presentation.review_target,
        presentation_mode: "diff",
        source_code: "value = 0",
        modified_code: "value = total / count",
        source_hash: "b".repeat(64),
        modified_hash: "c".repeat(64),
        hunks: [{
          hunk_id: "diff.h1",
          header: "@@ -1,1 +1,1 @@",
          source_start: 1,
          source_count: 1,
          modified_start: 1,
          modified_count: 1,
          lines: [
            { line_key: "h1.l1", kind: "removed", text: "value = 0", source_line: 1, modified_line: null },
            { line_key: "h1.l2", kind: "added", text: "value = total / count", source_line: null, modified_line: 1 },
          ],
        }],
      },
    };

    render(<ModelCodeReviewArtifact artifact={diff} onAction={vi.fn()} />);

    expect(await screen.findByTestId("diff-editor")).toHaveTextContent("value = 0");
    expect(screen.getByTestId("diff-editor")).toHaveTextContent("value = total / count");
  });

  it("clears scored findings when the learner changes to uncertain", async () => {
    const onAction = vi.fn().mockResolvedValue(undefined);
    render(<ModelCodeReviewArtifact artifact={artifact()} onAction={onAction} />);

    fireEvent.click(screen.getByRole("button", { name: "添加发现" }));
    expect(screen.getByRole("group", { name: /发现 1/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "证据不足" }));
    expect(screen.queryByRole("group", { name: /发现 1/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "完成审查" }));

    await waitFor(() => expect(onAction).toHaveBeenCalledTimes(1));
    expect(onAction.mock.calls[0][0].payload.review_submission).toMatchObject({
      verdict: "uncertain",
      findings: [],
    });
  });

  it("maps only a complete range inside one published hunk", () => {
    const hunks = [{
      hunk_id: "diff.h1",
      header: "@@ -1,1 +1,1 @@",
      source_start: 1,
      source_count: 1,
      modified_start: 1,
      modified_count: 1,
      lines: [
        { line_key: "h1.l1", kind: "removed" as const, text: "value = 0", source_line: 1, modified_line: null },
        { line_key: "h1.l2", kind: "added" as const, text: "value = 1", source_line: null, modified_line: 1 },
      ],
    }, {
      hunk_id: "diff.h2",
      header: "@@ -10,1 +10,1 @@",
      source_start: 10,
      source_count: 1,
      modified_start: 10,
      modified_count: 1,
      lines: [
        { line_key: "h2.l1", kind: "removed" as const, text: "return false", source_line: 10, modified_line: null },
        { line_key: "h2.l2", kind: "added" as const, text: "return true", source_line: null, modified_line: 10 },
      ],
    }];

    expect(mapModelReviewSelection(hunks, "source", 1, 1)).toEqual({
      hunkId: "diff.h1", side: "source", startLine: 1, endLine: 1,
    });
    expect(mapModelReviewSelection(hunks, "modified", 1, 10)).toBeNull();
    expect(mapModelReviewSelection(hunks, "modified", 2, 2)).toBeNull();
    expect(mapModelReviewSelection(hunks, "modified", 10, 10)).toEqual({
      hunkId: "diff.h2", side: "modified", startLine: 10, endLine: 10,
    });
  });

  it("fails closed when an active review does not advertise complete_review", () => {
    const unauthorized = artifact();
    unauthorized.allowed_actions = ["cancel"];

    render(<ModelCodeReviewArtifact artifact={unauthorized} onAction={vi.fn()} />);

    expect(screen.getByRole("alert")).toHaveTextContent("ARTIFACT_ACTION_CONTRACT_ERROR");
    expect(screen.queryByRole("button", { name: "完成审查" })).not.toBeInTheDocument();
  });

});
