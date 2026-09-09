import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { LessonExerciseGateBlock, LessonGateBoundItem } from "../../../types";
import { LessonGatePanel } from "../lesson/LessonGatePanel";

const block: LessonExerciseGateBlock = {
  block_id: "gate-block-1",
  order_index: 0,
  citation_ids: [],
  type: "exercise_gate",
  gate_key: "python.variables.basic",
  gate_kind: "knowledge_check",
  assessment_contract_version: "lesson-gate-v1",
  required_capabilities: ["python.variables.binding"],
  learner_prompt: "完成理解检查。",
};

const choiceOptions = [
  { option_id: "prints_draft", label: "draft" },
  { option_id: "prints_published", label: "published" },
];

function knowledgeGate(responseKind: string, options: Array<{ option_id: string; label: string }> = []): LessonGateBoundItem {
  return {
    gate_key: block.gate_key,
    gate_kind: block.gate_kind,
    assessment_contract_version: block.assessment_contract_version,
    required_capabilities: block.required_capabilities,
    learner_prompt: block.learner_prompt,
    binding_id: "binding-1",
    binding_contract_hash: "a".repeat(64),
    requirement_kind: "required",
    pass_policy_version: "gate-pass-v1",
    pass_threshold: 0.8,
    execution_requirement: "forbidden",
    status: "available",
    gate_version: 1,
    attempt_count: 0,
    best_score: 0,
    latest_attempt_id: null,
    passed_at: null,
    execution_tier: "static_only",
    execution_disclosure: "此题只进行静态答案检查。",
    allowed_actions: ["submit"],
    exercise: {
      exercise_version_id: "exercise-version-1",
      exercise_key: "python.variables.rebinding-remediation",
      exercise_type: "static_code_reasoning",
      version: "v1",
      title: "变量重绑定检查",
      learner_prompt: {
        schema_version: "knowledge_check_prompt_v1",
        prompt_markdown: "What does this program print?\n\n```python\nlabel = \"draft\"\nprint(label)\n```",
        response_kind: responseKind,
        options,
      },
      starter_artifact: {
        schema_version: "knowledge_check_artifact_v1",
        response_kind: responseKind,
        options,
      },
      required_capabilities: ["python.variables.binding"],
      content_hash: "b".repeat(64),
    },
    latest_result: null,
  };
}

function renderGate(gate: LessonGateBoundItem, editorValue = "", onEditorChange = vi.fn()) {
  render(<LessonGatePanel
    block={block}
    gate={gate}
    editorValue={editorValue}
    reviewDraft={null}
    reviewEvidence={null}
    hint={null}
    attempt={null}
    resultStale={false}
    busyAction={null}
    errorMessage={null}
    onEditorChange={onEditorChange}
    onReviewDraftChange={vi.fn()}
    onPrepare={vi.fn()}
    onHint={vi.fn()}
    onRun={vi.fn()}
    onSubmit={vi.fn()}
    onEvidence={vi.fn()}
    onPoll={vi.fn()}
  />);
  return onEditorChange;
}

describe("LessonGatePanel knowledge prompts", () => {
  it.each(["single_choice", "single_select"])("renders %s as a controlled single-select and stores the public option id", (responseKind) => {
    const onEditorChange = renderGate(knowledgeGate(responseKind, choiceOptions), "prints_draft");

    expect(screen.getByText("What does this program print?")).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.tagName === "CODE" && element.textContent?.includes('label = "draft"') === true)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "draft" })).toBeChecked();

    fireEvent.click(screen.getByRole("radio", { name: "published" }));
    expect(onEditorChange).toHaveBeenCalledWith("prints_published");
    expect(screen.getByRole("button", { name: "提交检查" })).toBeEnabled();
  });

  it.each([
    ["short_text", "你的回答"],
    ["prediction", "你的预测"],
  ])("renders the supported %s response through the existing editor value", (responseKind, label) => {
    const onEditorChange = renderGate(knowledgeGate(responseKind), "1");
    const editor = screen.getByRole("textbox", { name: label });

    expect(editor).toHaveValue("1");
    fireEvent.change(editor, { target: { value: "updated answer" } });
    expect(onEditorChange).toHaveBeenCalledWith("updated answer");
  });

  it("fails closed for an unsupported knowledge response shape", () => {
    renderGate(knowledgeGate("multiple_choice", choiceOptions));

    expect(screen.getByRole("alert")).toHaveTextContent("公开回答格式暂不受支持");
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "提交检查" })).not.toBeInTheDocument();
  });

  it("uses the server disclosure and makes a no-action historical editor read-only", () => {
    const disclosure = "此 Gate 因已发布 binding contract 不兼容而不可用。";
    const gate: LessonGateBoundItem = {
      ...knowledgeGate("short_text"),
      execution_requirement: "required",
      execution_tier: "unavailable",
      execution_disclosure: disclosure,
      allowed_actions: [],
      exercise: {
        exercise_version_id: "exercise-version-legacy",
        exercise_key: "python.variables.legacy-code",
        exercise_type: "code_completion",
        version: "v1",
        title: "历史代码练习",
        learner_prompt: { text: "修复这段代码。" },
        starter_artifact: { content: "print(value)" },
        required_capabilities: ["python.variables.binding"],
        content_hash: "c".repeat(64),
      },
    };

    renderGate(gate, "print(value)");

    expect(screen.getByRole("textbox", { name: "练习编辑区" })).toBeDisabled();
    expect(screen.getByText(disclosure)).toBeInTheDocument();
    expect(screen.queryByText(/当前没有可验证执行环境/)).not.toBeInTheDocument();
  });
});
