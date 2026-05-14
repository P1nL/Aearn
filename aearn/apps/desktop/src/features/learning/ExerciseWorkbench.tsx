import type {
  AsyncActionState,
  ExerciseRunMode,
  WorkbenchState,
} from "../../appTypes";
import type {
  ExplainErrorResponse,
  ExplanationCheckResponse,
  ExplanationFocus,
  HintLevel,
  HintResponse,
  LearningExercise,
  LearningSessionResponse,
  RunExerciseResponse,
  SubmitExerciseResponse,
} from "../../types";
import { runtimeLabel, workbenchStateLabel } from "../../lib/desktopLabels";
import { RuntimeFeedback } from "./RuntimeFeedback";
import { HintHistoryCard } from "./HintHistoryCard";
import { ErrorFeedbackPane } from "./ErrorFeedbackPane";
import { ExplanationCheckPanel } from "./ExplanationCheckPanel";
import { SubmissionSummary } from "./SubmissionSummary";

type ExerciseWorkbenchProps = {
  session: LearningSessionResponse;
  exercise: LearningExercise;
  code: string;
  filledBlanks: Record<string, string>;
  lastRun: RunExerciseResponse | null;
  lastRunMode: ExerciseRunMode | null;
  lastSubmit: SubmitExerciseResponse | null;
  actionState: AsyncActionState;
  isStale: boolean;
  hintUsageCount: number;
  errorCount: number;
  hintLevel: HintLevel;
  selectedBlankId: string;
  hintHistory: HintResponse[];
  explainErrorResult: ExplainErrorResponse | null;
  explanationText: string;
  explanationFocus: ExplanationFocus;
  explanationRound: number;
  explanationCheckResult: ExplanationCheckResponse | null;
  onCodeChange: (value: string) => void;
  onBlankChange: (blankKey: string, value: string) => void;
  onRunPreview: () => void;
  onRunVisibleTests: () => void;
  onSubmit: () => void;
  onHintLevelChange: (value: HintLevel) => void;
  onSelectedBlankChange: (value: string) => void;
  onRequestHint: () => void;
  onExplainError: () => void;
  onExplanationTextChange: (value: string) => void;
  onExplanationFocusChange: (value: ExplanationFocus) => void;
  onCheckExplanation: () => void;
  onRetryAction: () => void;
  onOpenPublishDrawer: () => void;
};

export function ExerciseWorkbench({
  session,
  exercise,
  code,
  filledBlanks,
  lastRun,
  lastRunMode,
  lastSubmit,
  actionState,
  isStale,
  hintUsageCount,
  errorCount,
  hintLevel,
  selectedBlankId,
  hintHistory,
  explainErrorResult,
  explanationText,
  explanationFocus,
  explanationRound,
  explanationCheckResult,
  onCodeChange,
  onBlankChange,
  onRunPreview,
  onRunVisibleTests,
  onSubmit,
  onHintLevelChange,
  onSelectedBlankChange,
  onRequestHint,
  onExplainError,
  onExplanationTextChange,
  onExplanationFocusChange,
  onCheckExplanation,
  onRetryAction,
  onOpenPublishDrawer,
}: ExerciseWorkbenchProps) {
  const runtimeUnsupported = exercise.runtime_profile.runtime_tier === "compiled_sandbox_later";
  const hasFailedRun =
    lastRun !== null &&
    (lastRun.runtime_status !== "success" || lastRun.test_results.some((item) => !item.passed));
  const submitDisabled =
    runtimeUnsupported ||
    lastRun === null ||
    lastRunMode !== "visible_tests" ||
    isStale ||
    lastRun.runtime_status === "unsupported";
  const hintDisabled = runtimeUnsupported || lastRun === null || isStale || selectedBlankId.length === 0;
  const explainDisabled = runtimeUnsupported || lastRun === null || isStale || !hasFailedRun;
  const checkDisabled = runtimeUnsupported || lastRun === null || isStale || explanationText.trim().length === 0;
  const workbenchState: WorkbenchState = runtimeUnsupported
    ? "unsupported"
    : actionState.status === "loading"
      ? "running"
      : lastSubmit
        ? "submitted"
        : isStale
          ? "dirty"
          : "pristine";
  const actionError = actionState.status === "error" ? actionState : null;

  return (
    <section className="exercise-workbench">
      <div className="exercise-head">
        <div>
          <div className="kicker">Runtime Slice</div>
          <h2>{exercise.title}</h2>
        </div>
        <div className="workbench-head-meta">
          <span className="runtime-pill">{runtimeLabel(exercise.runtime_profile.runtime_tier)}</span>
          <span className={`editor-state editor-state-${workbenchState}`}>{workbenchStateLabel(workbenchState)}</span>
        </div>
      </div>

      <div className="thread-meta">
        <span>阶段：{session.context_snapshot.current_stage}</span>
        <span>知识点：{session.context_snapshot.KnowledgePoint.title}</span>
        <span>题型：{exercise.exercise_type}</span>
        <span>提示 {hintUsageCount} 次</span>
        <span>错误 {errorCount} 次</span>
      </div>

      <div className="exercise-grid">
        <article className="panel pad stack exercise-panel">
          <div className="tool-card">题面：{exercise.prompt_markdown}</div>

          {exercise.code_blanks.length > 0 && (
            <div className="blank-grid">
              {exercise.code_blanks.map((blank) => (
                <label className="blank-card" key={blank.id}>
                  <span>{blank.blank_key}</span>
                  <strong>{blank.expected_concept}</strong>
                  <input
                    value={filledBlanks[blank.blank_key] ?? ""}
                    placeholder={blank.placeholder}
                    onChange={(event) => onBlankChange(blank.blank_key, event.target.value)}
                    disabled={actionState.status === "loading"}
                  />
                </label>
              ))}
            </div>
          )}

          <label className="exercise-editor">
            <span>代码区</span>
            <textarea className="drawer-editor code-editor" value={code} onChange={(event) => onCodeChange(event.target.value)} />
          </label>
          <p className="meta">运行和提交前会自动把 `__BLANK_x__` 占位符替换成上方空缺输入。</p>

          {runtimeUnsupported && (
            <div className="draft-boundary">当前课程属于 compiled_sandbox_later。本切片只展示静态补全，不开放完整编译运行与最终提交评分。</div>
          )}
        </article>

        <article className="panel pad stack exercise-panel">
          <div className="action-row action-row-wrap">
            {exercise.runtime_profile.runtime_tier === "browser_preview" && (
              <button
                className="btn primary"
                type="button"
                disabled={runtimeUnsupported || actionState.status === "loading"}
                onClick={onRunPreview}
              >
                运行预览
              </button>
            )}
            <button
              className="btn primary"
              type="button"
              disabled={runtimeUnsupported || actionState.status === "loading"}
              onClick={onRunVisibleTests}
            >
              运行可见测试
            </button>
            <button className="btn primary ghost-btn" type="button" disabled={submitDisabled || actionState.status === "loading"} onClick={onSubmit}>
              提交结果
            </button>
            <button className="btn primary ghost-btn" type="button" onClick={onOpenPublishDrawer}>
              复盘草稿
            </button>
          </div>

          <div className="action-row action-row-wrap assist-row">
            <label className="inline-select">
              <span>提示目标</span>
              <select
                value={selectedBlankId}
                disabled={hintDisabled || actionState.status === "loading"}
                onChange={(event) => onSelectedBlankChange(event.target.value)}
              >
                {exercise.code_blanks.map((blank) => (
                  <option key={blank.id} value={blank.blank_key}>
                    {blank.blank_key}
                  </option>
                ))}
              </select>
            </label>
            <label className="inline-select">
              <span>提示层级</span>
              <select value={hintLevel} disabled={hintDisabled || actionState.status === "loading"} onChange={(event) => onHintLevelChange(event.target.value as HintLevel)}>
                <option value="nudge">nudge</option>
                <option value="concept">concept</option>
                <option value="code_shape">code_shape</option>
              </select>
            </label>
            <button className="btn primary ghost-btn" type="button" disabled={hintDisabled || actionState.status === "loading"} onClick={onRequestHint}>
              获取提示
            </button>
            <button className="btn primary ghost-btn" type="button" disabled={explainDisabled || actionState.status === "loading"} onClick={onExplainError}>
              解释错误
            </button>
          </div>

          <label className="exercise-editor explanation-editor">
            <span>解释关键代码</span>
            <textarea
              className="drawer-editor explanation-textarea"
              value={explanationText}
              placeholder="用自己的话解释关键代码、边界条件，或为什么这次修改能修复错误。"
              onChange={(event) => onExplanationTextChange(event.target.value)}
            />
          </label>

          <div className="action-row action-row-wrap">
            <label className="inline-select">
              <span>检查焦点</span>
              <select value={explanationFocus} disabled={runtimeUnsupported || actionState.status === "loading"} onChange={(event) => onExplanationFocusChange(event.target.value as ExplanationFocus)}>
                <option value="core_logic">core_logic</option>
                <option value="boundary_condition">boundary_condition</option>
                <option value="ai_generated_change">ai_generated_change</option>
              </select>
            </label>
            <div className="tool-chip">当前轮次 {explanationRound} / 2</div>
            <button className="btn primary ghost-btn" type="button" disabled={checkDisabled || actionState.status === "loading"} onClick={onCheckExplanation}>
              检查解释
            </button>
          </div>

          {actionState.status === "loading" && <div className="tool-card">{actionState.label}</div>}
          {actionError && (
            <div className="draft-boundary action-error">
              <div>
                {actionError.code}: {actionError.message}
              </div>
              {actionError.recoverable && (
                <button className="btn primary ghost-btn" type="button" onClick={onRetryAction}>
                  重试上一步
                </button>
              )}
            </div>
          )}
          {isStale && lastRun && <div className="draft-boundary">你已经修改了代码，下面的结果来自上一次运行，请先重新运行。</div>}
          {submitDisabled && lastRunMode === "preview" && <div className="draft-boundary">提交前需要先跑一次“运行可见测试”，预览结果不会直接进入评分。</div>}
          {submitDisabled && !lastRun && <div className="draft-boundary">先运行一次，拿到当前 Attempt 后才能提交评分、获取提示或检查解释。</div>}

          {!lastRun && !lastSubmit && <div className="empty-block">先运行一次，右侧会出现预览、stdout、测试结果和提交摘要。</div>}

          {hintHistory.length > 0 && <HintHistoryCard items={hintHistory} />}
          {explainErrorResult && <ErrorFeedbackPane result={explainErrorResult} />}
          {explanationCheckResult && <ExplanationCheckPanel result={explanationCheckResult} />}
          {lastRun && <RuntimeFeedback result={lastRun} runMode={lastRunMode} />}
          {lastSubmit && <SubmissionSummary result={lastSubmit} />}
        </article>
      </div>
    </section>
  );
}
