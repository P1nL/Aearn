import { lazy, Suspense, useMemo, useState } from "react";
import type { DiffOnMount, OnMount } from "@monaco-editor/react";

import type {
  ModelReviewDiffHunkV2,
  ModelReviewErrorCategoryV2,
  ModelReviewFindingV2,
  TutorPublicArtifactItem,
} from "../../../types";
import { Button } from "../../../ui/dsh-derived";
import { SafeMarkdown } from "./SafeMarkdown";
import type { TutorArtifactActionHandler } from "./artifactRendererTypes";

const MonacoEditor = lazy(() => import("@monaco-editor/react").then((module) => ({ default: module.default })));
const MonacoDiffEditor = lazy(() => import("@monaco-editor/react").then((module) => ({ default: module.DiffEditor })));

const CATEGORIES: Array<{ value: ModelReviewErrorCategoryV2; label: string }> = [
  { value: "requirements_drift", label: "需求偏离" },
  { value: "fabricated_api", label: "虚构 API / 假设" },
  { value: "logic_boundary", label: "逻辑与边界" },
  { value: "contract_integration", label: "契约集成" },
  { value: "async_lifecycle", label: "异步状态生命周期" },
  { value: "security_trust", label: "安全信任边界" },
  { value: "error_false_success", label: "错误处理 / 虚假成功" },
  { value: "weak_testing", label: "弱测试（专题）" },
];

export function ModelCodeReviewArtifact({
  artifact,
  onAction,
  actionBusy = false,
}: {
  artifact: TutorPublicArtifactItem;
  onAction?: TutorArtifactActionHandler;
  actionBusy?: boolean;
}) {
  const presentation = artifact.presentation;
  if (presentation.type !== "model_code_review_v2") {
    return <div className="inline-artifact-contract-error" role="alert">ARTIFACT_PRESENTATION_CONTRACT_ERROR</div>;
  }
  const reviewPresentation = presentation;
  const target = reviewPresentation.review_target;
  const enabledCategories = CATEGORIES.filter((item) =>
    reviewPresentation.review_categories.includes(item.value)
  );
  const defaultCategory = enabledCategories.find((item) => item.value === "logic_boundary")?.value
    ?? enabledCategories[0]?.value
    ?? "logic_boundary";
  const [verdict, setVerdict] = useState<"correctness_issue" | "no_correctness_issue" | "uncertain">("uncertain");
  const [findings, setFindings] = useState<ModelReviewFindingV2[]>([]);
  const [selection, setSelection] = useState(() => defaultSelection(target.hunks));
  const locked = reviewPresentation.submission_locked || artifact.state === "completed";
  const errors = validateReview(verdict, findings);
  const actionAuthorized = artifact.allowed_actions.includes("complete_review");
  const modelBase = `inmemory://aearn/${encodeURIComponent(artifact.conversation_id)}/${encodeURIComponent(artifact.id)}`;
  const editorOptions = useMemo(() => ({
    ariaLabel: "AI 代码审查，只读",
    readOnly: true,
    automaticLayout: true,
    minimap: { enabled: false },
    scrollBeyondLastLine: false,
    wordWrap: "on" as const,
    fontSize: 13,
    lineHeight: 21,
    renderSideBySide: true,
    originalEditable: false,
    padding: { top: 10, bottom: 10 },
  }), []);
  if (!locked && !actionAuthorized) {
    return <div className="inline-artifact-contract-error" role="alert">ARTIFACT_ACTION_CONTRACT_ERROR</div>;
  }

  function selectRange(side: "source" | "modified", startLine: number, endLine: number) {
    setSelection(mapModelReviewSelection(target.hunks, side, startLine, endLine));
  }

  const mountCode: OnMount = (editor) => {
    editor.onDidChangeCursorSelection((event) => {
      selectRange("modified", event.selection.startLineNumber, event.selection.endLineNumber);
    });
  };
  const mountDiff: DiffOnMount = (editor) => {
    editor.getOriginalEditor().onDidChangeCursorSelection((event) => {
      selectRange("source", event.selection.startLineNumber, event.selection.endLineNumber);
    });
    editor.getModifiedEditor().onDidChangeCursorSelection((event) => {
      selectRange("modified", event.selection.startLineNumber, event.selection.endLineNumber);
    });
  };

  function addFinding() {
    if (!selection || locked || findings.length >= 12) return;
    setVerdict("correctness_issue");
    setFindings((current) => [...current, {
      client_finding_id: `finding-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${current.length + 1}`}`,
      hunk_id: selection.hunkId,
      side: selection.side,
      start_line: selection.startLine,
      end_line: selection.endLine,
      category: defaultCategory,
      severity: "medium",
      explanation: "",
    }]);
  }

  async function submitReview() {
    if (!onAction || locked || actionBusy || errors.length > 0) return;
    await onAction({
      artifact,
      action: "complete_review",
      payload: {
        action: "complete_review",
        review_submission: {
          schema_version: "model_code_review_submission_v2",
          presentation_hash: reviewPresentation.presentation_hash,
          verdict,
          findings,
        },
      },
    });
  }

  return <section className={`artifact-model-review${locked ? " locked" : ""}`} aria-label="AI 代码审查">
    <header className="artifact-model-review-toolbar">
      <div><strong>{target.runtime_label}</strong><span>{target.language_id} · {target.presentation_mode === "diff" ? `${target.hunks.length} 个变更块` : `${target.line_count} 行`}</span></div>
      <span>只读</span>
    </header>
    <div className="artifact-model-review-monaco" data-review-mode={target.presentation_mode}>
      <Suspense fallback={<div className="code-editor-loading" role="status">正在加载审查视图…</div>}>
        {target.presentation_mode === "diff" && target.source_code !== null
          ? <MonacoDiffEditor
              original={target.source_code}
              modified={target.modified_code}
              originalModelPath={`${modelBase}/source`}
              modifiedModelPath={`${modelBase}/modified`}
              language={monacoLanguage(target.language_id)}
              theme="light"
              keepCurrentOriginalModel
              keepCurrentModifiedModel
              onMount={mountDiff}
              options={editorOptions}
            />
          : <MonacoEditor
              path={`${modelBase}/code`}
              value={target.modified_code}
              language={monacoLanguage(target.language_id)}
              theme="light"
              keepCurrentModel
              onMount={mountCode}
              options={editorOptions}
            />}
      </Suspense>
    </div>
    {!locked ? <>
      <div className="artifact-model-review-selection" aria-live="polite">
        <span>{selection ? `${selection.side === "source" ? "原始" : "修改后"} L${selection.startLine}–L${selection.endLine} · ${selection.hunkId}` : "请先在代码中选择范围"}</span>
        <Button variant="outline" disabled={!selection || findings.length >= 12} onClick={addFinding}>添加发现</Button>
      </div>
      <fieldset className="artifact-model-review-verdict">
        <legend>总体结论</legend>
        <label><input type="radio" checked={verdict === "correctness_issue"} onChange={() => setVerdict("correctness_issue")} />存在可验证问题</label>
        <label><input type="radio" checked={verdict === "no_correctness_issue"} onChange={() => { setVerdict("no_correctness_issue"); setFindings([]); }} />未发现可验证问题</label>
        <label><input type="radio" checked={verdict === "uncertain"} onChange={() => { setVerdict("uncertain"); setFindings([]); }} />证据不足</label>
      </fieldset>
      <div className="artifact-model-review-findings">
        {findings.map((finding, index) => <FindingEditor
          key={finding.client_finding_id}
          finding={finding}
          index={index}
          categories={enabledCategories}
          onChange={(next) => setFindings((current) => current.map((item, itemIndex) => itemIndex === index ? next : item))}
          onRemove={() => setFindings((current) => current.filter((_, itemIndex) => itemIndex !== index))}
        />)}
      </div>
      {errors.length > 0 ? <ul className="artifact-model-review-errors" aria-live="polite">{errors.map((error) => <li key={error}>{error}</li>)}</ul> : null}
      <footer className="artifact-model-review-footer"><span>评分仅覆盖可验证错误；风格建议不决定结果。</span><Button variant="primary" busy={actionBusy} disabled={!onAction || actionBusy || errors.length > 0} onClick={() => void submitReview()}>完成审查</Button></footer>
    </> : <section className={`artifact-model-review-result ${reviewPresentation.outcome ?? ""}`} aria-live="polite">
      <header><strong>{reviewPresentation.outcome === "passed" ? "审查通过" : "需要补救"}</strong><span>{Math.round((reviewPresentation.score ?? 0) * 100)}%</span></header>
      <SafeMarkdown markdown={reviewPresentation.evaluation_markdown} surface="artifact" />
      {reviewPresentation.remediation_handle ? <small>下一步将使用已发布的范围更小或难度更低变体。</small> : null}
    </section>}
  </section>;
}

function FindingEditor({ finding, index, categories, onChange, onRemove }: {
  finding: ModelReviewFindingV2;
  index: number;
  categories: Array<{ value: ModelReviewErrorCategoryV2; label: string }>;
  onChange: (finding: ModelReviewFindingV2) => void;
  onRemove: () => void;
}) {
  return <fieldset className="artifact-model-review-finding">
    <legend>发现 {index + 1} · {finding.side === "source" ? "原始" : "修改后"} L{finding.start_line}–L{finding.end_line}</legend>
    <button type="button" onClick={onRemove} aria-label={`删除发现 ${index + 1}`}>删除</button>
    <label><span>错误类别</span><select value={finding.category} onChange={(event) => onChange({ ...finding, category: event.target.value as ModelReviewErrorCategoryV2 })}>{categories.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
    <label><span>严重程度</span><select value={finding.severity} onChange={(event) => onChange({ ...finding, severity: event.target.value as ModelReviewFindingV2["severity"] })}><option value="info">提示</option><option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="critical">严重</option></select></label>
    <label className="wide"><span>简短说明</span><textarea rows={3} maxLength={1200} value={finding.explanation} onChange={(event) => onChange({ ...finding, explanation: event.target.value })} placeholder="说明触发条件、违反的明确契约和可能影响。" /></label>
  </fieldset>;
}

export function mapModelReviewSelection(
  hunks: ModelReviewDiffHunkV2[],
  side: "source" | "modified",
  startLine: number,
  endLine: number,
) {
  if (startLine < 1 || endLine < startLine) return null;
  const hunk = hunks.find((item) => {
    const mapped = new Set(item.lines.flatMap((line) => {
      const number = side === "source" ? line.source_line : line.modified_line;
      return number === null ? [] : [number];
    }));
    for (let line = startLine; line <= endLine; line += 1) {
      if (!mapped.has(line)) return false;
    }
    return true;
  });
  return hunk ? { hunkId: hunk.hunk_id, side, startLine, endLine } : null;
}

function defaultSelection(hunks: ModelReviewDiffHunkV2[]) {
  for (const hunk of hunks) {
    const line = hunk.lines.find((item) => item.modified_line !== null) ?? hunk.lines.find((item) => item.source_line !== null);
    if (!line) continue;
    const side = line.modified_line !== null ? "modified" as const : "source" as const;
    const lineNumber = line.modified_line ?? line.source_line ?? 1;
    return { hunkId: hunk.hunk_id, side, startLine: lineNumber, endLine: lineNumber };
  }
  return null;
}

function validateReview(verdict: "correctness_issue" | "no_correctness_issue" | "uncertain", findings: ModelReviewFindingV2[]) {
  const errors: string[] = [];
  if (verdict === "correctness_issue" && findings.length === 0) errors.push("存在问题时至少添加一条定位发现。");
  if (verdict !== "correctness_issue" && findings.length > 0) errors.push("非问题结论不能保留评分 finding。");
  if (findings.some((item) => item.explanation.trim().length < 8)) errors.push("每条发现需要至少 8 个字符的可验证说明。");
  if (new Set(findings.map((item) => item.client_finding_id)).size !== findings.length) errors.push("finding 标识必须唯一。");
  return errors;
}

function monacoLanguage(languageId: string): string {
  return { javascript: "javascript", js: "javascript", typescript: "typescript", ts: "typescript", python: "python", sql: "sql", html: "html", css: "css" }[languageId] ?? "plaintext";
}
