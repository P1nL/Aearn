import type {
  ExerciseAttemptState,
  LessonExerciseGateBlock,
  LessonGateBoundItem,
  ModelCodeReviewExercise,
  ModelCodeReviewSubmission,
  ModelReviewEvidenceResponse,
  ModelReviewFinding,
  ModelReviewVerdict,
} from "../../../types";
import { ModelCodeReviewFindingEditor } from "./ModelCodeReviewFindingEditor";
import { ModelCodeReviewResult } from "./ModelCodeReviewResult";

type ModelCodeReviewPanelProps = {
  block: LessonExerciseGateBlock; gate: LessonGateBoundItem; exercise: ModelCodeReviewExercise; draft: ModelCodeReviewSubmission;
  hint: import("../../../types").LessonGateHint | null; attempt: ExerciseAttemptState | null; evidence: ModelReviewEvidenceResponse | null; resultStale: boolean;
  busyAction: "hint" | "submit" | "evidence" | "poll" | null; errorMessage: string | null;
  onDraftChange: (draft: ModelCodeReviewSubmission) => void; onHint: () => void; onSubmit: () => void;
  onEvidence: () => void; onPoll: () => void;
};

export function ModelCodeReviewPanel({ block, gate, exercise, draft, hint, attempt, evidence, resultStale, busyAction, errorMessage, onDraftChange, onHint, onSubmit, onEvidence, onPoll }: ModelCodeReviewPanelProps) {
  const artifact = exercise.starter_artifact;
  const prompt = exercise.learner_prompt;
  const findingErrors = draft.findings.map((finding) => validateFinding(finding, artifact.line_count));
  const formErrors = validateSubmission(draft, findingErrors);
  const result = attempt?.result ?? gate.latest_result;
  const historyOnly = !attempt && gate.latest_result !== null;
  const disabled = gate.status === "passed" || busyAction !== null;
  const updateFinding = (index: number, finding: ModelReviewFinding) => {
    onDraftChange({ ...draft, findings: draft.findings.map((item, itemIndex) => itemIndex === index ? finding : item) });
  };
  const addFinding = () => onDraftChange({ ...draft, findings: [...draft.findings, createFinding(artifact.line_count)] });

  return (
    <section className="lesson-block lesson-gate lesson-gate-panel model-review-panel" aria-labelledby={`gate-title-${block.block_id}`}>
      <div className="lesson-gate-heading-row"><div><p className="tutor-panel-eyebrow">模型输出审核 · 确定性评分</p><h2 id={`gate-title-${block.block_id}`}>{exercise.title}</h2><p>{prompt.learner_instruction}</p></div><span className={`lesson-gate-state ${gate.status}`}>{gate.status === "passed" ? "已通过" : gate.status === "remediation_required" ? "需要补救" : gate.status === "in_progress" ? "进行中" : "可开始"}</span></div>
      <div className="model-review-brief">
        <div><strong>需求</strong><ul>{prompt.requirements.map((item) => <li key={item}>{item}</li>)}</ul></div>
        <div><strong>审核范围</strong><p>{prompt.review_scope.join(" · ")}</p><small>{gate.execution_disclosure}</small></div>
      </div>
      <figure className="model-review-code"><figcaption><span>{artifact.language_id}</span><strong>{artifact.runtime_label}</strong><small>{artifact.line_count} 行 · 发布前已验证</small></figcaption><ol>{artifact.model_code.replace(/\r\n?/g, "\n").split("\n").map((line, index) => <li key={index}><code>{line || " "}</code></li>)}</ol></figure>
      <fieldset className="model-review-verdict" disabled={disabled}><legend>总体结论</legend>{VERDICTS.map((option) => <label key={option.value}><input type="radio" name={`verdict-${gate.gate_key}`} value={option.value} checked={draft.verdict === option.value} onChange={() => onDraftChange({ ...draft, verdict: option.value })} /><span><strong>{option.label}</strong><small>{option.description}</small></span></label>)}</fieldset>
      <div className="model-review-findings-heading"><div><strong>结构化发现</strong><span>最多 12 条；只提交你能说明触发条件、影响和验证方法的发现。</span></div><button className="tutor-compact-button quiet" type="button" disabled={disabled || draft.findings.length >= 12} onClick={addFinding}>添加发现</button></div>
      {draft.findings.length === 0 ? <p className="model-review-no-findings">当前没有 finding。选择“存在正确性问题”或“仅有改进建议”时需要添加相应发现。</p> : draft.findings.map((finding, index) => <ModelCodeReviewFindingEditor key={finding.client_finding_id} finding={finding} index={index} lineCount={artifact.line_count} disabled={disabled} errors={findingErrors[index]} onChange={(next) => updateFinding(index, next)} onRemove={() => onDraftChange({ ...draft, findings: draft.findings.filter((_, itemIndex) => itemIndex !== index) })} />)}
      <label className="model-review-note"><span>总体补充说明（可选）</span><textarea rows={3} maxLength={2000} disabled={disabled} value={draft.supplemental_note ?? ""} onChange={(event) => onDraftChange({ ...draft, supplemental_note: event.target.value || null })} /></label>
      {formErrors.length > 0 ? <ul className="model-review-form-errors" aria-live="polite">{formErrors.map((error) => <li key={error}>{error}</li>)}</ul> : null}
      {hint ? <aside className="lesson-gate-hint" aria-live="polite"><span>提示 {hint.hint_level}</span><p>{safeHintText(hint.safe_hint)}</p></aside> : null}
      <div className="lesson-gate-actions" aria-label="模型代码审核操作">
        {gate.allowed_actions.includes("hint") ? <button className="tutor-compact-button quiet" type="button" disabled={busyAction !== null} onClick={onHint}>{busyAction === "hint" ? "正在请求提示……" : "获得提示"}</button> : null}
        <button className="tutor-compact-button quiet" type="button" disabled={busyAction !== null} onClick={onEvidence}>{busyAction === "evidence" ? "正在读取……" : "查看发布前验证证据"}</button>
        {gate.allowed_actions.includes("submit") ? <button className="tutor-primary-button" type="button" disabled={disabled || formErrors.length > 0 || attempt?.status === "pending"} onClick={onSubmit}>{busyAction === "submit" ? "正在提交……" : "提交审核"}</button> : null}
      </div>
      {evidence ? <aside className="model-review-evidence" aria-live="polite"><div><strong>发布前验证证据</strong><span>查看后本次练习会标记为 assisted；这些证据只展示安全检查摘要，不展示私有验证内容或评分答案。</span></div><ul>{evidence.evidence.checks.map((check) => <li key={check.check_type}><span>{evidenceCheckLabel(check.check_type)}</span><strong>{check.status === "passed" ? "通过" : "不适用"}</strong><small>{check.safe_code}</small></li>)}</ul></aside> : null}
      {attempt?.status === "pending" ? <div className="lesson-gate-pending" role="status"><span className="lesson-status-pulse" aria-hidden="true" /><div><strong>正在读取同一 Attempt</strong><p>不会创建第二份提交。</p></div><button className="tutor-compact-button quiet" type="button" disabled={busyAction !== null} onClick={onPoll}>{busyAction === "poll" ? "正在刷新……" : "刷新结果"}</button></div> : null}
      {result && isModelReviewResult(result) ? <ModelCodeReviewResult result={result} stale={resultStale || historyOnly} historyOnly={historyOnly} /> : null}
      {errorMessage ? <p className="lesson-gate-error" role="alert">{errorMessage}</p> : null}
    </section>
  );
}

const VERDICTS: Array<{ value: ModelReviewVerdict; label: string; description: string }> = [
  { value: "correctness_issue", label: "存在正确性问题", description: "至少提交一条 correctness finding。" },
  { value: "no_correctness_issue", label: "未发现正确性问题", description: "可以保持 findings 为空，或只记录改进。" },
  { value: "improvement_only", label: "仅有改进建议", description: "至少提交一条 improvement finding。" },
  { value: "uncertain", label: "证据不足，暂不确定", description: "可提交已有证据并明确不确定性。" },
];
function createFinding(lineCount: number): ModelReviewFinding {
  return { client_finding_id: `finding-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`}`, finding_kind: "correctness", start_line: 1, end_line: Math.min(1, lineCount), category: "correctness", severity: "medium", trigger_condition: "", principle: "", impact: "", validation_method: "", suggested_fix: "", supplemental_note: null };
}
function validateFinding(finding: ModelReviewFinding, lineCount: number): string[] {
  const errors: string[] = [];
  if (!Number.isInteger(finding.start_line) || finding.start_line < 1 || finding.start_line > lineCount) errors.push("起始行超出代码范围。");
  if (!Number.isInteger(finding.end_line) || finding.end_line < finding.start_line || finding.end_line > lineCount) errors.push("结束行必须位于起始行之后且不超过代码范围。");
  if (!/^[A-Za-z0-9][A-Za-z0-9._:@-]{0,119}$/.test(finding.category)) errors.push("分类键只能使用字母、数字、点、下划线、冒号、@ 或连字符。");
  for (const [label, value] of [["触发条件", finding.trigger_condition], ["违反原则", finding.principle], ["可能影响", finding.impact], ["验证方法", finding.validation_method], ["建议修复", finding.suggested_fix]] as const) if (!value.trim()) errors.push(`${label}不能为空。`);
  if (finding.finding_kind === "improvement" && !["info", "low"].includes(finding.severity)) errors.push("改进建议的严重程度只能是提示或低。");
  return errors;
}
function validateSubmission(draft: ModelCodeReviewSubmission, findingErrors: string[][]): string[] {
  const errors: string[] = [];
  const correctness = draft.findings.filter((item) => item.finding_kind === "correctness").length;
  const improvements = draft.findings.length - correctness;
  if (findingErrors.some((items) => items.length > 0)) errors.push("请先修正每条 finding 的字段错误。");
  if (draft.verdict === "correctness_issue" && correctness === 0) errors.push("“存在正确性问题”需要至少一条正确性发现。");
  if (draft.verdict === "no_correctness_issue" && correctness > 0) errors.push("“未发现正确性问题”不能包含正确性发现。");
  if (draft.verdict === "improvement_only" && (improvements === 0 || correctness > 0)) errors.push("“仅有改进建议”需要至少一条改进发现，且不能包含正确性发现。");
  if (new Set(draft.findings.map((item) => item.client_finding_id)).size !== draft.findings.length) errors.push("finding 标识必须唯一。");
  return errors;
}
function isModelReviewResult(result: NonNullable<ExerciseAttemptState["result"]>): result is NonNullable<ExerciseAttemptState["result"]> & { safe_feedback: import("../../../types").ModelReviewSafeFeedback } { return result.safe_feedback.status === "model_code_review_evaluated"; }
function safeHintText(payload: Record<string, unknown>): string { const value = payload.message ?? payload.text ?? payload.summary; return typeof value === "string" && value.trim() ? value : "服务器已提供一条有界提示。"; }
function evidenceCheckLabel(value: ModelReviewEvidenceResponse["evidence"]["checks"][number]["check_type"]): string { return { parser: "解析", compile_or_typecheck: "编译/类型检查", visible_tests: "可见测试", hidden_tests: "隐藏测试", coverage: "覆盖度" }[value]; }
