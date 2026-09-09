import type {
  ExerciseAttemptState,
  LessonExerciseGateBlock,
  LessonGateHint,
  LessonGateItem,
  LessonGateResult,
  ModelCodeReviewSubmission,
  ModelReviewEvidenceResponse,
} from "../../../types";
import { SafeMarkdown } from "../../tutor/artifacts/SafeMarkdown";
import { ModelCodeReviewPanel } from "./ModelCodeReviewPanel";

type GateBusyAction = "prepare" | "hint" | "run" | "submit" | "evidence" | "poll" | null;

type KnowledgeCheckOption = { optionId: string; label: string };
type SupportedKnowledgePrompt = {
  promptMarkdown: string;
  responseKind: "single_select" | "short_text" | "prediction";
  options: KnowledgeCheckOption[];
};

type LessonGatePanelProps = {
  block: LessonExerciseGateBlock;
  gate: LessonGateItem | null;
  editorValue: string;
  reviewDraft: ModelCodeReviewSubmission | null;
  reviewEvidence: ModelReviewEvidenceResponse | null;
  hint: LessonGateHint | null;
  attempt: ExerciseAttemptState | null;
  resultStale: boolean;
  busyAction: GateBusyAction;
  errorMessage: string | null;
  onEditorChange: (value: string) => void;
  onReviewDraftChange: (draft: ModelCodeReviewSubmission) => void;
  onPrepare: () => void;
  onHint: () => void;
  onRun: () => void;
  onSubmit: () => void;
  onEvidence: () => void;
  onPoll: () => void;
};

export function LessonGatePanel({
  block, gate, editorValue, reviewDraft, reviewEvidence, hint, attempt, resultStale,
  busyAction, errorMessage, onEditorChange, onReviewDraftChange, onPrepare, onHint,
  onRun, onSubmit, onEvidence, onPoll,
}: LessonGatePanelProps) {
  if (!gate) {
    return (
      <section className="lesson-block lesson-gate lesson-gate-panel" aria-busy="true">
        <GateHeader block={block} />
        <p className="lesson-gate-boundary">正在核对 frozen assignment 与 Gate binding……</p>
      </section>
    );
  }

  if (!isBoundLessonGate(gate)) {
    const canPrepare = gate.allowed_actions.includes("prepare") && gate.status !== "preparing";
    const run = gate.review_authoring_run;
    return (
      <section className="lesson-block lesson-gate lesson-gate-panel" aria-busy={gate.status === "preparing"}>
        <GateHeader block={block} />
        <dl className="lesson-gate-facts">
          <GateFact label="教学形态" value={gateKindLabel(gate.gate_kind)} />
          <GateFact label="评估 Contract" value={gate.assessment_contract_version} />
          <GateFact label="能力范围" value={gate.required_capabilities.join("、")} />
        </dl>
        <div className="lesson-gate-empty">
          <div>
            <strong>{gate.status === "preparing" ? "正在生成并验证练习" : gate.status === "failed" ? "练习准备未完成" : "练习尚未绑定"}</strong>
            <p>{gate.status === "preparing" ? "候选题目通过受控 Action 与 executor 预发布验证后才会绑定；页面会自动刷新。" : gate.status === "failed" ? (run?.failure_message ?? "未发布半成品，请重试准备。") : "服务器会把此 slot 绑定到 exact exercise version；前端不会自行生成题目。"}</p>
            {run?.failure_code ? <code>{run.failure_code}</code> : null}
          </div>
          {canPrepare ? <button className="tutor-primary-button" type="button" disabled={busyAction !== null} onClick={onPrepare}>{busyAction === "prepare" ? "正在准备……" : gate.status === "failed" ? "重试准备" : "准备练习"}</button> : null}
        </div>
        {errorMessage ? <p className="lesson-gate-error" role="alert">{errorMessage}</p> : null}
      </section>
    );
  }

  const exercise = gate.exercise;
  if (exercise.exercise_type === "model_code_review") {
    if (!reviewDraft) {
      return <section className="lesson-block lesson-gate lesson-gate-panel" aria-busy="true"><GateHeader block={block} /><p className="lesson-gate-boundary">正在初始化结构化审核草稿……</p></section>;
    }
    return (
      <ModelCodeReviewPanel
        block={block}
        gate={gate}
        exercise={exercise}
        draft={reviewDraft}
        hint={hint}
        attempt={attempt}
        evidence={reviewEvidence}
        resultStale={resultStale}
        busyAction={busyAction === "prepare" || busyAction === "run" ? null : busyAction}
        errorMessage={errorMessage}
        onDraftChange={onReviewDraftChange}
        onHint={onHint}
        onSubmit={onSubmit}
        onEvidence={onEvidence}
        onPoll={onPoll}
      />
    );
  }

  const result = attempt?.result ?? gate.latest_result;
  const historyOnly = !attempt && gate.latest_result !== null;
  const knowledgePromptCandidate = exercise.exercise_type === "static_code_reasoning"
    && (exercise.learner_prompt.schema_version === "knowledge_check_prompt_v1"
      || exercise.starter_artifact.schema_version === "knowledge_check_artifact_v1");
  const knowledgePrompt = knowledgePromptCandidate
    ? supportedKnowledgePrompt(exercise.learner_prompt, exercise.starter_artifact)
    : null;
  const knowledgePromptMismatch = knowledgePromptCandidate && knowledgePrompt === null;
  const responseAuthorized = gate.allowed_actions.includes("run") || gate.allowed_actions.includes("submit");
  const editorDisabled = gate.status === "passed" || busyAction !== null || !responseAuthorized;
  const showGenericEditor = !knowledgePromptCandidate
    && (exercise.exercise_type !== "static_code_reasoning" || gate.allowed_actions.includes("submit"));
  const showGateActions = !knowledgePromptMismatch && gate.allowed_actions.some((action) => action === "hint" || action === "run" || action === "submit");

  return (
    <section className="lesson-block lesson-gate lesson-gate-panel" aria-labelledby={`gate-title-${block.block_id}`}>
      <div className="lesson-gate-heading-row">
        <div>
          <p className="tutor-panel-eyebrow">{requirementLabel(gate.requirement_kind)} · {gateKindLabel(gate.gate_kind)}</p>
          <h2 id={`gate-title-${block.block_id}`}>{exercise.title}</h2>
          {knowledgePrompt
            ? <SafeMarkdown markdown={knowledgePrompt.promptMarkdown} surface="artifact" />
            : <p>{promptText(exercise.learner_prompt, gate.learner_prompt)}</p>}
        </div>
        <span className={`lesson-gate-state ${gate.status}`}>{gateStateLabel(gate.status)}</span>
      </div>

      <div className="lesson-gate-tier" data-tier={gate.execution_tier}>
        <strong>{executionTierLabel(gate.execution_tier)}</strong>
        <span>{gate.execution_disclosure}</span>
      </div>

      <dl className="lesson-gate-facts">
        <GateFact label="通过阈值" value={`${Math.round(gate.pass_threshold * 100)}%`} />
        <GateFact label="尝试次数" value={String(gate.attempt_count)} />
        <GateFact label="能力范围" value={exercise.required_capabilities?.join("、") ?? gate.required_capabilities.join("、")} />
      </dl>

      {knowledgePrompt?.responseKind === "single_select" ? (
        <fieldset className="lesson-gate-editor knowledge-check-options" disabled={editorDisabled}>
          <legend className="sr-only">请选择一个答案</legend>
          {knowledgePrompt.options.map((option) => (
            <label key={option.optionId}>
              <input
                type="radio"
                name={`lesson-gate-${block.block_id}`}
                value={option.optionId}
                checked={editorValue === option.optionId}
                onChange={() => onEditorChange(option.optionId)}
              />
              <span>{option.label}</span>
            </label>
          ))}
        </fieldset>
      ) : knowledgePrompt?.responseKind === "short_text" || knowledgePrompt?.responseKind === "prediction" ? (
        <label className="lesson-gate-editor">
          <span>{knowledgePrompt.responseKind === "prediction" ? "你的预测" : "你的回答"}</span>
          <textarea
            aria-label={knowledgePrompt.responseKind === "prediction" ? "你的预测" : "你的回答"}
            value={editorValue}
            rows={Math.min(16, Math.max(7, editorValue.split("\n").length + 2))}
            spellCheck={false}
            disabled={editorDisabled}
            onChange={(event) => onEditorChange(event.target.value)}
          />
        </label>
      ) : showGenericEditor ? (
        <label className="lesson-gate-editor">
          <span>{exercise.exercise_type === "static_code_reasoning" ? "你的回答" : "练习编辑区"}</span>
          <textarea value={editorValue} rows={Math.min(16, Math.max(7, editorValue.split("\n").length + 2))} spellCheck={false} disabled={editorDisabled} onChange={(event) => onEditorChange(event.target.value)} />
        </label>
      ) : null}

      {knowledgePromptMismatch ? <p className="lesson-gate-boundary" role="alert">当前知识检查的公开回答格式暂不受支持，已停止本地作答与提交。</p> : null}

      {hint ? <aside className="lesson-gate-hint" aria-live="polite"><span>提示 {hint.hint_level}</span><p>{safeFeedbackText(hint.safe_hint, "服务器已提供一条有界提示。")}</p></aside> : null}

      {showGateActions ? <div className="lesson-gate-actions" aria-label="练习操作">
        {gate.allowed_actions.includes("hint") ? <button className="tutor-compact-button quiet" type="button" disabled={busyAction !== null} onClick={onHint}>{busyAction === "hint" ? "正在请求提示……" : "获得提示"}</button> : null}
        {gate.allowed_actions.includes("run") ? <button className="tutor-compact-button quiet" type="button" disabled={busyAction !== null || attempt?.status === "pending" || !editorValue.trim()} onClick={onRun}>{busyAction === "run" ? "正在进入执行队列……" : "运行"}</button> : null}
        {gate.allowed_actions.includes("submit") ? <button className="tutor-primary-button" type="button" disabled={busyAction !== null || attempt?.status === "pending" || !editorValue.trim()} onClick={onSubmit}>{busyAction === "submit" ? "正在提交……" : "提交检查"}</button> : null}
      </div> : null}

      {gate.execution_tier === "static_only" ? <p className="lesson-gate-boundary">此练习只做确定性静态评估，不声称代码已编译、运行或通过测试。</p> : null}
      {attempt?.status === "pending" ? <div className="lesson-gate-pending" role="status"><span className="lesson-status-pulse" aria-hidden="true" /><div><strong>已进入受控执行队列</strong><p>页面只读取同一 Attempt 的 learner-safe 结果，不会创建第二次提交。</p></div><button className="tutor-compact-button quiet" type="button" disabled={busyAction !== null} onClick={onPoll}>{busyAction === "poll" ? "正在刷新……" : "刷新结果"}</button></div> : null}
      {result ? <GateResultView result={result} stale={resultStale || historyOnly} historyOnly={historyOnly} /> : null}
      {errorMessage ? <p className="lesson-gate-error" role="alert">{errorMessage}</p> : null}
    </section>
  );
}

function isBoundLessonGate(gate: LessonGateItem): gate is import("../../../types").LessonGateBoundItem {
  return gate.status !== "unbound" && gate.status !== "preparing" && gate.status !== "failed";
}

function GateHeader({ block }: { block: LessonExerciseGateBlock }) { return <div><p className="tutor-panel-eyebrow">练习 Gate</p><h2>理解检查</h2><p>{block.learner_prompt}</p></div>; }
function GateFact({ label, value }: { label: string; value: string }) { return <div><dt>{label}</dt><dd>{value || "—"}</dd></div>; }
function GateResultView({ result, stale, historyOnly }: { result: LessonGateResult; stale: boolean; historyOnly: boolean }) {
  const stdout = stringField(result.safe_feedback, "stdout");
  const stderr = stringField(result.safe_feedback, "stderr");
  return <section className={`lesson-gate-result ${result.outcome}`} aria-live="polite"><div><span>{stale ? (historyOnly ? "历史结果" : "结果已过期") : "当前结果"}</span><strong>{outcomeLabel(result.outcome)} · {Math.round(result.score * 100)}%</strong></div><p>{safeFeedbackText(result.safe_feedback, "服务器已记录本次练习结果。")}</p>{stdout ? <pre><code>{stdout}</code></pre> : null}{stderr ? <pre className="lesson-gate-stderr"><code>{stderr}</code></pre> : null}{stale ? <p className="lesson-gate-stale">编辑区内容已变化，或这是服务器记录的上一份提交；请勿把它当作当前答案的结果。</p> : null}</section>;
}
function promptText(payload: Record<string, unknown>, fallback: string): string { return stringField(payload, "text") ?? stringField(payload, "prompt") ?? stringField(payload, "prompt_markdown") ?? fallback; }
function safeFeedbackText(payload: Record<string, unknown>, fallback: string): string { return stringField(payload, "message") ?? stringField(payload, "text") ?? stringField(payload, "summary") ?? fallback; }
function stringField(payload: Record<string, unknown>, key: string): string | null { const value = payload[key]; return typeof value === "string" && value.trim() ? value : null; }
function supportedKnowledgePrompt(prompt: Record<string, unknown>, artifact: Record<string, unknown>): SupportedKnowledgePrompt | null {
  if (
    !hasExactKeys(prompt, ["schema_version", "prompt_markdown", "response_kind", "options"])
    || !hasExactKeys(artifact, ["schema_version", "response_kind", "options"])
    || prompt.schema_version !== "knowledge_check_prompt_v1"
    || artifact.schema_version !== "knowledge_check_artifact_v1"
    || typeof prompt.prompt_markdown !== "string"
    || !prompt.prompt_markdown.trim()
    || prompt.response_kind !== artifact.response_kind
  ) return null;
  const promptOptions = knowledgeCheckOptions(prompt.options);
  const artifactOptions = knowledgeCheckOptions(artifact.options);
  if (!promptOptions || !artifactOptions || !sameKnowledgeCheckOptions(promptOptions, artifactOptions)) return null;
  if (prompt.response_kind === "single_choice" || prompt.response_kind === "single_select") {
    return promptOptions.length >= 2 && promptOptions.length <= 12
      ? { promptMarkdown: prompt.prompt_markdown, responseKind: "single_select", options: promptOptions }
      : null;
  }
  if (prompt.response_kind === "short_text" || prompt.response_kind === "prediction") {
    return promptOptions.length === 0
      ? { promptMarkdown: prompt.prompt_markdown, responseKind: prompt.response_kind, options: [] }
      : null;
  }
  return null;
}
function knowledgeCheckOptions(value: unknown): KnowledgeCheckOption[] | null {
  if (!Array.isArray(value)) return null;
  const options: KnowledgeCheckOption[] = [];
  for (const item of value) {
    if (!isRecord(item) || !hasExactKeys(item, ["option_id", "label"]) || typeof item.option_id !== "string" || !item.option_id.trim() || typeof item.label !== "string" || !item.label.trim()) return null;
    options.push({ optionId: item.option_id, label: item.label });
  }
  return new Set(options.map((option) => option.optionId)).size === options.length ? options : null;
}
function sameKnowledgeCheckOptions(left: KnowledgeCheckOption[], right: KnowledgeCheckOption[]): boolean {
  return left.length === right.length && left.every((option, index) => option.optionId === right[index]?.optionId && option.label === right[index]?.label);
}
function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
function hasExactKeys(value: Record<string, unknown>, keys: string[]): boolean {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}
function gateKindLabel(kind: LessonExerciseGateBlock["gate_kind"]): string { return { knowledge_check: "知识检查", guided_practice: "引导练习", independent_practice: "独立练习" }[kind]; }
function requirementLabel(kind: "required" | "recommended" | "diagnostic"): string { return { required: "必修 Gate", recommended: "推荐练习", diagnostic: "诊断练习" }[kind]; }
function gateStateLabel(state: "available" | "in_progress" | "passed" | "remediation_required"): string { return { available: "可开始", in_progress: "进行中", passed: "已通过", remediation_required: "需要补救" }[state]; }
function executionTierLabel(tier: "teaching_local" | "container_verified" | "static_only" | "unavailable"): string { return { teaching_local: "开发教学执行", container_verified: "受审容器执行", static_only: "静态评估", unavailable: "执行不可用" }[tier]; }
function outcomeLabel(outcome: LessonGateResult["outcome"]): string { return { passed: "通过", failed: "未通过", timed_out: "执行超时", cancelled: "已取消", unavailable: "执行不可用", invalid: "结果无效" }[outcome]; }
