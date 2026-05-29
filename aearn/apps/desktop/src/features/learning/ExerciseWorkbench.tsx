import { useState } from "react";
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
import { CodeEditor } from "./CodeEditor";
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
  onOpenNoteDrawer: () => void;
};

type AssistTab = "hints" | "explain" | "check";

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
  onOpenNoteDrawer,
}: ExerciseWorkbenchProps) {
  const [assistTab, setAssistTab] = useState<AssistTab>("hints");

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
  const isLoading = actionState.status === "loading";

  return (
    <section className="exercise-workbench">
      <div className="wb-header">
        <div className="wb-header-left">
          <span className="wb-kicker">{"练习"}</span>
          <h2 className="wb-title">{exercise.title}</h2>
        </div>
        <div className="wb-header-right">
          <span className="wb-meta-pill">{exercise.exercise_type}</span>
          <span className="wb-meta-pill">{runtimeLabel(exercise.runtime_profile.runtime_tier)}</span>
          <span className={`wb-state wb-state-${workbenchState}`}>{workbenchStateLabel(workbenchState)}</span>
        </div>
      </div>

      <div className="wb-context-bar">
        <span>{session.context_snapshot.current_stage}</span>
        <span className="wb-context-sep" />
        <span>{session.context_snapshot.KnowledgePoint.title}</span>
        <span className="wb-context-sep" />
        <span>{"提示"} {hintUsageCount}</span>
        <span className="wb-context-sep" />
        <span>{"错误"} {errorCount}</span>
      </div>

      <div className="wb-split">
        {/* Left: Editor pane */}
        <div className="wb-editor-pane">
          <div className="wb-prompt">{exercise.prompt_markdown}</div>

          {exercise.code_blanks.length > 0 && (
            <div className="wb-blanks">
              {exercise.code_blanks.map((blank) => (
                <label className="wb-blank" key={blank.id}>
                  <span className="wb-blank-key">{blank.blank_key}</span>
                  <input
                    className="wb-blank-input"
                    value={filledBlanks[blank.blank_key] ?? ""}
                    placeholder={blank.placeholder}
                    onChange={(event) => onBlankChange(blank.blank_key, event.target.value)}
                    disabled={isLoading}
                  />
                </label>
              ))}
            </div>
          )}

          <div className="wb-editor-frame">
            <div className="wb-editor-toolbar">
              <div className="wb-editor-toolbar-left">
                <span className="wb-editor-lang">{exercise.runtime_profile.language}</span>
              </div>
              <div className="wb-editor-toolbar-right">
                {exercise.runtime_profile.runtime_tier === "browser_preview" && (
                  <button className="wb-toolbar-btn" type="button" disabled={runtimeUnsupported || isLoading} onClick={onRunPreview}>
                    {"预览"}
                  </button>
                )}
                <button className="wb-toolbar-btn wb-toolbar-btn-primary" type="button" disabled={runtimeUnsupported || isLoading} onClick={onRunVisibleTests}>
                  {"运行"}
                </button>
                <button className="wb-toolbar-btn" type="button" disabled={submitDisabled || isLoading} onClick={onSubmit}>
                  {"提交"}
                </button>
                <button className="wb-toolbar-btn" type="button" onClick={onOpenNoteDrawer}>
                  {"笔记"}
                </button>
              </div>
            </div>
            <CodeEditor
              language={exercise.runtime_profile.language}
              value={code}
              onChange={onCodeChange}
              readOnly={isLoading || runtimeUnsupported}
              height="400px"
              dark
            />
          </div>

          {runtimeUnsupported && (
            <div className="wb-notice">{"当前课程暂不支持完整编译运行，只展示静态补全练习。"}</div>
          )}

          {/* Assist tabs below editor */}
          <div className="wb-assist">
            <div className="wb-assist-tabs">
              <button className={`wb-assist-tab ${assistTab === "hints" ? "active" : ""}`} type="button" onClick={() => setAssistTab("hints")}>
                {"提示"}
              </button>
              <button className={`wb-assist-tab ${assistTab === "explain" ? "active" : ""}`} type="button" onClick={() => setAssistTab("explain")}>
                {"错因分析"}
              </button>
              <button className={`wb-assist-tab ${assistTab === "check" ? "active" : ""}`} type="button" onClick={() => setAssistTab("check")}>
                {"解释检查"}
              </button>
            </div>
            <div className="wb-assist-body">
              {assistTab === "hints" && (
                <div className="wb-assist-panel">
                  <div className="wb-assist-controls">
                    <select className="wb-select" value={selectedBlankId} disabled={hintDisabled || isLoading} onChange={(e) => onSelectedBlankChange(e.target.value)}>
                      {exercise.code_blanks.map((blank) => (
                        <option key={blank.id} value={blank.blank_key}>{blank.blank_key}</option>
                      ))}
                    </select>
                    <select className="wb-select" value={hintLevel} disabled={hintDisabled || isLoading} onChange={(e) => onHintLevelChange(e.target.value as HintLevel)}>
                      <option value="nudge">{"轻推"}</option>
                      <option value="concept">{"概念"}</option>
                      <option value="code_shape">{"代码结构"}</option>
                    </select>
                    <button className="wb-toolbar-btn wb-toolbar-btn-primary" type="button" disabled={hintDisabled || isLoading} onClick={onRequestHint}>
                      {"获取提示"}
                    </button>
                  </div>
                  {hintHistory.length > 0 && <HintHistoryCard items={hintHistory} />}
                </div>
              )}
              {assistTab === "explain" && (
                <div className="wb-assist-panel">
                  <button className="wb-toolbar-btn wb-toolbar-btn-primary" type="button" disabled={explainDisabled || isLoading} onClick={onExplainError}>
                    {"分析错误原因"}
                  </button>
                  {explainErrorResult && <ErrorFeedbackPane result={explainErrorResult} />}
                </div>
              )}
              {assistTab === "check" && (
                <div className="wb-assist-panel">
                  <textarea
                    className="wb-explanation-input"
                    value={explanationText}
                    placeholder={"用自己的话解释关键代码、边界条件，或为什么这次修改能修复错误。"}
                    onChange={(e) => onExplanationTextChange(e.target.value)}
                  />
                  <div className="wb-assist-controls">
                    <select className="wb-select" value={explanationFocus} disabled={runtimeUnsupported || isLoading} onChange={(e) => onExplanationFocusChange(e.target.value as ExplanationFocus)}>
                      <option value="core_logic">{"核心逻辑"}</option>
                      <option value="boundary_condition">{"边界条件"}</option>
                      <option value="ai_generated_change">{"AI 生成变更"}</option>
                    </select>
                    <span className="wb-round-badge">{"第"} {explanationRound}/2 {"轮"}</span>
                    <button className="wb-toolbar-btn wb-toolbar-btn-primary" type="button" disabled={checkDisabled || isLoading} onClick={onCheckExplanation}>
                      {"检查解释"}
                    </button>
                  </div>
                  {explanationCheckResult && <ExplanationCheckPanel result={explanationCheckResult} />}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right: Output pane — clean, only results */}
        <div className="wb-output-pane">
          <div className="wb-output-header">
            <span className="wb-output-title">{"输出"}</span>
            {lastRun && (
              <span className={`wb-output-status ${lastRun.runtime_status === "success" && !hasFailedRun ? "success" : "error"}`}>
                {lastRun.runtime_status === "success" && !hasFailedRun ? "PASS" : "FAIL"}
              </span>
            )}
          </div>
          <div className="wb-output-body">
            {isLoading && <div className="wb-output-loading"><div className="wb-spinner" />{actionState.label}</div>}
            {actionError && (
              <div className="wb-output-error">
                <span>{actionError.code}: {actionError.message}</span>
                {actionError.recoverable && (
                  <button className="wb-toolbar-btn" type="button" onClick={onRetryAction}>{"重试"}</button>
                )}
              </div>
            )}
            {isStale && lastRun && <div className="wb-output-stale">{"代码已修改，请重新运行"}</div>}
            {!lastRun && !lastSubmit && !isLoading && (
              <div className="wb-output-empty">
                <div className="wb-output-empty-icon">{"▶"}</div>
                <p>{"点击运行查看输出结果"}</p>
              </div>
            )}
            {lastRun && <RuntimeFeedback result={lastRun} runMode={lastRunMode} />}
            {lastSubmit && <SubmissionSummary result={lastSubmit} />}
          </div>
        </div>
      </div>
    </section>
  );
}
