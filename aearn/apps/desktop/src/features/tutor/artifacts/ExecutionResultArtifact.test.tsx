import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  SafeExecutionResultV2,
  TutorArtifactAttemptDetailV1,
  TutorArtifactAttemptDetailV2,
  TutorArtifactOutcome,
  TutorPublicArtifactItem,
} from "../../../types";
import { InlineArtifactMessage } from "./InlineArtifactMessage";
import { resetArtifactUiStateCachesForTests } from "./artifactUiState";

const hash = (value: string) => value.repeat(64).slice(0, 64);

function resultArtifact(outcome: TutorArtifactOutcome = "failed"): TutorPublicArtifactItem {
  return {
    kind: "artifact",
    id: "artifact-result",
    conversation_id: "conversation-1",
    turn_id: "turn-result",
    learning_track_id: "track-1",
    knowledge_key: "javascript.variables",
    teaching_session_id: "teaching-session-1",
    checkpoint_id: "checkpoint-1",
    artifact_version: 1,
    artifact_kind: "test_result",
    purpose: "result",
    owner_kind: "teaching_practice",
    owner_id: "owner-1",
    owner_version: 1,
    state: "completed",
    blocking: false,
    title: "测试结果",
    instruction_markdown: outcome === "passed" ? "已完成。" : "请先处理未通过项。",
    difficulty: null,
    presentation: {
      type: "test_result_v1",
      attempt_id: "attempt-1",
      status: "terminal",
      outcome,
      passed_count: 2,
      total_count: outcome === "passed" ? 2 : 4,
      summary_markdown: outcome === "passed" ? "已完成。" : "请先处理未通过项。",
      result_hash: hash("a"),
    },
    allowed_actions: [],
    source_references: [{
      kind: "artifact",
      reference_id: "artifact-source",
      reference_version: 5,
      content_hash: hash("b"),
      label: "原代码工件",
    }],
    active_attempt: {
      attempt_id: "attempt-1",
      attempt_type: "run",
      status: "terminal",
      outcome,
      score: outcome === "passed" ? 1 : 0.5,
      result_hash: hash("a"),
      accepted_at: "2026-09-01T00:00:00Z",
      terminal_at: "2026-09-01T00:00:01Z",
    },
    branch_summary: null,
    version: 2,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:01Z",
    terminal_at: "2026-09-01T00:00:01Z",
  };
}

function executionResult(outcome: TutorArtifactOutcome = "failed"): SafeExecutionResultV2 {
  const passed = outcome === "passed";
  return {
    schema_version: "safe-execution-result-v2",
    status: "success",
    stdout: passed ? "" : "2 rows returned",
    stderr: passed ? "" : "Validation stopped after the bounded result.",
    test_feedback: passed ? [
      { case_id: "visible.one", passed: true, visible: true, message: "", duration_ms: 3, location: null },
      { case_id: "non-visible-1", passed: true, visible: false, message: "A non-visible scenario passed.", duration_ms: 2, location: null },
    ] : [
      { case_id: "visible.case", passed: false, visible: true, message: "Returned value did not match.", duration_ms: 7,
        location: { line: 4, column: 2, end_line: 4, end_column: 9 } },
      { case_id: "non-visible-1", passed: false, visible: false, message: "A non-visible scenario still failed.", duration_ms: 5, location: null },
    ],
    passed_test_count: 2,
    total_test_count: passed ? 2 : 4,
    duration_ms: 18,
    diagnostic_code: passed ? "execution_complete" : "visible_test_failure",
    presentation: passed
      ? { kind: "none" }
      : { kind: "table_result_v1", columns: ["id", "label"], rows: [[1, "alpha"], [2, null]] },
  };
}

function attemptV2(artifact: TutorPublicArtifactItem, outcome: TutorArtifactOutcome = "failed"): TutorArtifactAttemptDetailV2 {
  return {
    schema_version: "tutor_learning_artifact_attempt_v2",
    artifact_id: artifact.id,
    artifact_version: artifact.version,
    conversation_id: artifact.conversation_id,
    learning_track_id: artifact.learning_track_id,
    knowledge_key: artifact.knowledge_key,
    teaching_session_id: artifact.teaching_session_id,
    attempt_id: "attempt-1",
    attempt_type: "run",
    exercise_version_id: "exercise-1",
    submission_hash: hash("c"),
    independence: "independent",
    assistance_kind: "independent",
    status: "terminal",
    execution_job_state: "completed",
    accepted_at: "2026-09-01T00:00:00Z",
    result: {
      outcome,
      score: outcome === "passed" ? 1 : 0.5,
      execution_result: executionResult(outcome),
      capability_scores: { correctness: outcome === "passed" ? 1 : 0.5 },
      policy_version: "artifact.result.v2",
      result_hash: hash("a"),
      terminal_at: "2026-09-01T00:00:01Z",
    },
  };
}

function attemptV1(artifact: TutorPublicArtifactItem): TutorArtifactAttemptDetailV1 {
  return {
    ...attemptV2(artifact),
    schema_version: "tutor_learning_artifact_attempt_v1",
    result: {
      outcome: "failed",
      score: 0.5,
      safe_feedback: { summary: "Historical result" },
      capability_scores: { correctness: 0.5 },
      policy_version: "artifact.result.v1",
      result_hash: hash("a"),
      terminal_at: "2026-09-01T00:00:01Z",
    },
  };
}

describe("ExecutionResultArtifact", () => {
  beforeEach(() => {
    resetArtifactUiStateCachesForTests();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: vi.fn() });
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  });

  it("loads scoped Attempt v2 detail and renders failures before the merged passed count", async () => {
    const user = userEvent.setup();
    const artifact = resultArtifact();
    const loadAttempt = vi.fn().mockResolvedValue(attemptV2(artifact));
    const onReturnToSource = vi.fn();
    const rendered = render(<InlineArtifactMessage
      artifact={artifact}
      autoReveal
      loadAttempt={loadAttempt}
      onReturnToSource={onReturnToSource}
    />);

    expect(await screen.findByText("visible.case")).toBeInTheDocument();
    expect(screen.getByText("非公开测试")).toBeInTheDocument();
    expect(rendered.container).not.toHaveTextContent("non-visible-1");
    expect(screen.getByText("第 4 行，第 2 列 至 第 4 行，第 9 列")).toBeInTheDocument();
    const failure = screen.getByText("visible.case");
    const passedSummary = screen.getByText("其他 2 项通过");
    expect(failure.compareDocumentPosition(passedSummary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(rendered.container).not.toHaveTextContent("visible_test_failure");
    expect(screen.getAllByText("请先处理未通过项。")).toHaveLength(1);

    await user.click(screen.getByText("标准输出"));
    await user.click(screen.getByText("错误输出"));
    expect(screen.getByText("2 rows returned")).toBeInTheDocument();
    expect(screen.getByText("Validation stopped after the bounded result.")).toBeInTheDocument();
    const tableScroll = screen.getByLabelText("公开查询结果表格");
    expect(tableScroll).toHaveClass("execution-result-table-scroll");
    expect(screen.getByRole("columnheader", { name: "label" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "NULL" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "返回修改" }));
    expect(onReturnToSource).toHaveBeenCalledWith({
      resultArtifact: artifact,
      sourceArtifactReference: artifact.source_references[0],
    });
    expect(loadAttempt).toHaveBeenCalledWith({ artifact, attemptId: "attempt-1" });
    expect(screen.queryByRole("button", { name: /提交/ })).not.toBeInTheDocument();
  });

  it("omits empty output disclosures and return action for a passed result", async () => {
    const artifact = resultArtifact("passed");
    render(<InlineArtifactMessage artifact={artifact} autoReveal loadAttempt={vi.fn().mockResolvedValue(attemptV2(artifact, "passed"))} />);

    expect(await screen.findByText("全部通过")).toBeInTheDocument();
    expect(screen.queryByText("其他 2 项通过")).not.toBeInTheDocument();
    expect(screen.queryByText("标准输出")).not.toBeInTheDocument();
    expect(screen.queryByText("错误输出")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "返回修改" })).not.toBeInTheDocument();
  });

  it("keeps historical Attempt v1 readable without inspecting safe_feedback", async () => {
    const artifact = resultArtifact();
    render(<InlineArtifactMessage artifact={artifact} autoReveal loadAttempt={vi.fn().mockResolvedValue(attemptV1(artifact))} />);

    expect(await screen.findByText("历史结果已读取；详细执行明细未记录。")).toBeInTheDocument();
    expect(screen.queryByText("Historical result")).not.toBeInTheDocument();
  });

  it("fails closed when a typed loader returns another Artifact scope", async () => {
    const artifact = resultArtifact();
    const mismatched = { ...attemptV2(artifact), artifact_id: "artifact-other" };
    render(<InlineArtifactMessage artifact={artifact} autoReveal loadAttempt={vi.fn().mockResolvedValue(mismatched)} />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("ARTIFACT_ATTEMPT_CONTRACT_ERROR"));
    expect(screen.queryByText("visible.case")).not.toBeInTheDocument();
  });
});
