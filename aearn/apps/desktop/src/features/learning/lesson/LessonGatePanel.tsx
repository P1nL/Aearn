import type {
  ExerciseAttemptState,
  LessonExerciseGateBlock,
  LessonGateHint,
  LessonGateItem,
  LessonGateResult,
} from "../../../types";

type GateBusyAction = "prepare" | "hint" | "run" | "submit" | "poll" | null;

type LessonGatePanelProps = {
  block: LessonExerciseGateBlock;
  gate: LessonGateItem | null;
  editorValue: string;
  hint: LessonGateHint | null;
  attempt: ExerciseAttemptState | null;
  resultStale: boolean;
  busyAction: GateBusyAction;
  errorMessage: string | null;
  onEditorChange: (value: string) => void;
  onPrepare: () => void;
  onHint: () => void;
  onRun: () => void;
  onSubmit: () => void;
  onPoll: () => void;
};

export function LessonGatePanel({
  block,
  gate,
  editorValue,
  hint,
  attempt,
  resultStale,
  busyAction,
  errorMessage,
  onEditorChange,
  onPrepare,
  onHint,
  onRun,
  onSubmit,
  onPoll,
}: LessonGatePanelProps) {
  if (!gate) {
    return (
      <section className="lesson-block lesson-gate lesson-gate-panel" aria-busy="true">
        <GateHeader block={block} />
        <p className="lesson-gate-boundary">正在核对 frozen assignment 与 Gate binding……</p>
      </section>
    );
  }

  if (gate.status === "unbound") {
    const canPrepare = gate.allowed_actions.includes("prepare");
    return (
      <section className="lesson-block lesson-gate lesson-gate-panel">
        <GateHeader block={block} />
        <dl className="lesson-gate-facts">
          <GateFact label="教学形态" value={gateKindLabel(gate.gate_kind)} />
          <GateFact label="评估 Contract" value={gate.assessment_contract_version} />
          <GateFact label="能力范围" value={gate.required_capabilities.join("、")} />
        </dl>
        <div className="lesson-gate-empty">
          <div>
            <strong>练习尚未绑定</strong>
            <p>服务器会把此 slot 绑定到 exact exercise version；前端不会自行生成题目。</p>
          </div>
          {canPrepare ? (
            <button className="tutor-primary-button" type="button" disabled={busyAction !== null} onClick={onPrepare}>
              {busyAction === "prepare" ? "正在准备……" : "准备练习"}
            </button>
          ) : null}
        </div>
        {errorMessage ? <p className="lesson-gate-error" role="alert">{errorMessage}</p> : null}
      </section>
    );
  }

  const result = attempt?.result ?? gate.latest_result;
  const historyOnly = !attempt && gate.latest_result !== null;
  const showEditor = gate.exercise.exercise_type !== "static_code_reasoning" || gate.allowed_actions.includes("submit");
  const isUnavailable = gate.execution_tier === "unavailable";

  return (
    <section className="lesson-block lesson-gate lesson-gate-panel" aria-labelledby={`gate-title-${block.block_id}`}>
      <div className="lesson-gate-heading-row">
        <div>
          <p className="tutor-panel-eyebrow">{requirementLabel(gate.requirement_kind)} · {gateKindLabel(gate.gate_kind)}</p>
          <h2 id={`gate-title-${block.block_id}`}>{gate.exercise.title}</h2>
          <p>{promptText(gate.exercise.learner_prompt, gate.learner_prompt)}</p>
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
        <GateFact label="能力范围" value={gate.exercise.required_capabilities?.join("、") ?? gate.required_capabilities.join("、")} />
      </dl>

      {showEditor ? (
        <label className="lesson-gate-editor">
          <span>{gate.exercise.exercise_type === "static_code_reasoning" ? "你的回答" : "练习编辑区"}</span>
          <textarea
            value={editorValue}
            rows={Math.min(16, Math.max(7, editorValue.split("\n").length + 2))}
            spellCheck={false}
            disabled={gate.status === "passed" || busyAction !== null}
            onChange={(event) => onEditorChange(event.target.value)}
          />
        </label>
      ) : null}

      {hint ? (
        <aside className="lesson-gate-hint" aria-live="polite">
          <span>提示 {hint.hint_level}</span>
          <p>{safeFeedbackText(hint.safe_hint, "服务器已提供一条有界提示。")}</p>
        </aside>
      ) : null}

      <div className="lesson-gate-actions" aria-label="练习操作">
        {gate.allowed_actions.includes("hint") ? (
          <button className="tutor-compact-button quiet" type="button" disabled={busyAction !== null} onClick={onHint}>
            {busyAction === "hint" ? "正在请求提示……" : "获得提示"}
          </button>
        ) : null}
        {gate.allowed_actions.includes("run") ? (
          <button className="tutor-compact-button quiet" type="button" disabled={busyAction !== null || attempt?.status === "pending" || !editorValue.trim()} onClick={onRun}>
            {busyAction === "run" ? "正在进入执行队列……" : "运行"}
          </button>
        ) : null}
        {gate.allowed_actions.includes("submit") ? (
          <button className="tutor-primary-button" type="button" disabled={busyAction !== null || attempt?.status === "pending" || !editorValue.trim()} onClick={onSubmit}>
            {busyAction === "submit" ? "正在提交……" : "提交检查"}
          </button>
        ) : null}
      </div>

      {isUnavailable ? (
        <p className="lesson-gate-boundary">当前没有可验证执行环境，因此没有显示依赖执行的 Run/Submit；系统未回退到本机运行。</p>
      ) : gate.execution_tier === "static_only" ? (
        <p className="lesson-gate-boundary">此练习只做确定性静态评估，不声称代码已编译、运行或通过测试。</p>
      ) : null}

      {attempt?.status === "pending" ? (
        <div className="lesson-gate-pending" role="status">
          <span className="lesson-status-pulse" aria-hidden="true" />
          <div><strong>已进入受控执行队列</strong><p>页面只读取同一 Attempt 的 learner-safe 结果，不会创建第二次提交。</p></div>
          <button className="tutor-compact-button quiet" type="button" disabled={busyAction !== null} onClick={onPoll}>{busyAction === "poll" ? "正在刷新……" : "刷新结果"}</button>
        </div>
      ) : null}

      {result ? (
        <GateResultView result={result} stale={resultStale || historyOnly} historyOnly={historyOnly} />
      ) : null}
      {errorMessage ? <p className="lesson-gate-error" role="alert">{errorMessage}</p> : null}
    </section>
  );
}

function GateHeader({ block }: { block: LessonExerciseGateBlock }) {
  return <div><p className="tutor-panel-eyebrow">练习 Gate</p><h2>理解检查</h2><p>{block.learner_prompt}</p></div>;
}

function GateFact({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value || "—"}</dd></div>;
}

function GateResultView({ result, stale, historyOnly }: { result: LessonGateResult; stale: boolean; historyOnly: boolean }) {
  const stdout = stringField(result.safe_feedback, "stdout");
  const stderr = stringField(result.safe_feedback, "stderr");
  return (
    <section className={`lesson-gate-result ${result.outcome}`} aria-live="polite">
      <div>
        <span>{stale ? (historyOnly ? "历史结果" : "结果已过期") : "当前结果"}</span>
        <strong>{outcomeLabel(result.outcome)} · {Math.round(result.score * 100)}%</strong>
      </div>
      <p>{safeFeedbackText(result.safe_feedback, "服务器已记录本次练习结果。")}</p>
      {stdout ? <pre><code>{stdout}</code></pre> : null}
      {stderr ? <pre className="lesson-gate-stderr"><code>{stderr}</code></pre> : null}
      {stale ? <p className="lesson-gate-stale">编辑区内容已变化，或这是服务器记录的上一份提交；请勿把它当作当前答案的结果。</p> : null}
    </section>
  );
}

function promptText(payload: Record<string, unknown>, fallback: string): string {
  return stringField(payload, "text") ?? fallback;
}

function safeFeedbackText(payload: Record<string, unknown>, fallback: string): string {
  return stringField(payload, "message") ?? stringField(payload, "text") ?? stringField(payload, "summary") ?? fallback;
}

function stringField(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function gateKindLabel(kind: LessonExerciseGateBlock["gate_kind"]): string {
  return { knowledge_check: "知识检查", guided_practice: "引导练习", independent_practice: "独立练习" }[kind];
}

function requirementLabel(kind: "required" | "recommended" | "diagnostic"): string {
  return { required: "必修 Gate", recommended: "推荐练习", diagnostic: "诊断练习" }[kind];
}

function gateStateLabel(state: "available" | "in_progress" | "passed" | "remediation_required"): string {
  return { available: "可开始", in_progress: "进行中", passed: "已通过", remediation_required: "需要补救" }[state];
}

function executionTierLabel(tier: "teaching_local" | "container_verified" | "static_only" | "unavailable"): string {
  return {
    teaching_local: "开发教学执行",
    container_verified: "受审容器执行",
    static_only: "静态评估",
    unavailable: "执行不可用",
  }[tier];
}

function outcomeLabel(outcome: LessonGateResult["outcome"]): string {
  return {
    passed: "通过",
    failed: "未通过",
    timed_out: "执行超时",
    cancelled: "已取消",
    unavailable: "执行不可用",
    invalid: "结果无效",
  }[outcome];
}
