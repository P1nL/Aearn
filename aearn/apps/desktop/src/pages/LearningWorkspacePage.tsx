import { startTransition, useEffect, useState } from "react";

import {
  checkLearningExplanation,
  explainLearningError,
  requestLearningHint,
  runLearningExercise,
  submitLearningExercise,
} from "../api";
import type {
  AsyncActionState,
  ConversationMessage,
  ExerciseActionKind,
  ExerciseRunMode,
  SessionState,
} from "../appTypes";
import { ExerciseWorkbench } from "../features/learning/ExerciseWorkbench";
import { SystemCard } from "../components/SystemCard";
import { ThreadMessages } from "../components/ThreadMessages";
import {
  initialBlankState,
  materializeExerciseCode,
  toActionError,
} from "../lib/learningHelpers";
import type {
  CreatedPlanResponse,
  ExplainErrorResponse,
  ExplanationCheckResponse,
  ExplanationFocus,
  HintLevel,
  HintResponse,
  RunExerciseResponse,
  SubmitExerciseResponse,
} from "../types";

type LearningWorkspacePageProps = {
  createdPlan: CreatedPlanResponse | null;
  sessionState: SessionState;
  messages: ConversationMessage[];
  lastRun: RunExerciseResponse | null;
  lastSubmit: SubmitExerciseResponse | null;
  resetNonce: number;
  onOpenLearningSession: (planResponse: CreatedPlanResponse, knowledgePointId: string) => Promise<void> | void;
  onRunChange: (run: RunExerciseResponse | null) => void;
  onSubmitChange: (submit: SubmitExerciseResponse | null) => void;
  onKnowledgePointUpdate: (patch: SubmitExerciseResponse["KnowledgePoint"]) => void;
  onOpenNoteDrawer: () => void;
};

export function LearningWorkspacePage({
  createdPlan,
  sessionState,
  messages,
  lastRun,
  lastSubmit,
  resetNonce,
  onOpenLearningSession,
  onRunChange,
  onSubmitChange,
  onKnowledgePointUpdate,
  onOpenNoteDrawer,
}: LearningWorkspacePageProps) {
  const [exerciseActionState, setExerciseActionState] = useState<AsyncActionState>({ status: "idle" });
  const [editorCode, setEditorCode] = useState("");
  const [filledBlanks, setFilledBlanks] = useState<Record<string, string>>({});
  const [isStale, setIsStale] = useState(false);
  const [lastRunMode, setLastRunMode] = useState<ExerciseRunMode | null>(null);
  const [lastExerciseAction, setLastExerciseAction] = useState<ExerciseActionKind | null>(null);
  const [hintUsageCount, setHintUsageCount] = useState(0);
  const [errorCount, setErrorCount] = useState(0);
  const [hintLevel, setHintLevel] = useState<HintLevel>("nudge");
  const [selectedBlankId, setSelectedBlankId] = useState("");
  const [hintHistory, setHintHistory] = useState<HintResponse[]>([]);
  const [explainErrorResult, setExplainErrorResult] = useState<ExplainErrorResponse | null>(null);
  const [explanationText, setExplanationText] = useState("");
  const [explanationFocus, setExplanationFocus] = useState<ExplanationFocus>("core_logic");
  const [explanationRound, setExplanationRound] = useState(1);
  const [explanationCheckResult, setExplanationCheckResult] = useState<ExplanationCheckResponse | null>(null);

  const session = sessionState.status === "ready" ? sessionState.data : null;
  const activeExercise = session?.exercise ?? null;

  function resetWorkbenchState(nextCode = "", nextBlanks: Record<string, string> = {}, nextSelectedBlankId = "") {
    setEditorCode(nextCode);
    setFilledBlanks(nextBlanks);
    setExerciseActionState({ status: "idle" });
    setIsStale(false);
    setLastRunMode(null);
    setLastExerciseAction(null);
    setHintUsageCount(0);
    setErrorCount(0);
    setHintLevel("nudge");
    setSelectedBlankId(nextSelectedBlankId);
    setHintHistory([]);
    setExplainErrorResult(null);
    setExplanationText("");
    setExplanationFocus("core_logic");
    setExplanationRound(1);
    setExplanationCheckResult(null);
  }

  useEffect(() => {
    if (session && activeExercise) {
      resetWorkbenchState(
        activeExercise.starter_code,
        initialBlankState(activeExercise),
        activeExercise.code_blanks[0]?.blank_key ?? "",
      );
      return;
    }
    resetWorkbenchState();
  }, [session?.session_id, activeExercise?.id, resetNonce]);

  async function handleRunExercise(runMode: ExerciseRunMode) {
    if (!session || !activeExercise) {
      return;
    }
    setLastExerciseAction(runMode === "preview" ? "run_preview" : "run_tests");
    const materializedCode = materializeExerciseCode(editorCode, filledBlanks);
    setExerciseActionState({
      status: "loading",
      label: runMode === "preview" ? "正在返回浏览器预览" : "正在运行可见测试",
    });
    try {
      const response = await runLearningExercise({
        sessionId: session.session_id,
        exerciseId: activeExercise.id,
        code: materializedCode,
        filledBlanks,
        runtimeProfileId: activeExercise.runtime_profile.id,
        runMode,
      });
      startTransition(() => {
        onRunChange(response);
        onSubmitChange(null);
        setLastRunMode(runMode);
        setExerciseActionState({ status: "idle" });
        setIsStale(false);
        setExplainErrorResult(null);
        setExplanationCheckResult(null);
        setExplanationRound(1);
        if (!response.idempotency_replayed && (response.runtime_status !== "success" || (runMode === "visible_tests" && response.test_pass_rate < 1))) {
          setErrorCount((current) => current + 1);
        }
      });
    } catch (error) {
      setExerciseActionState(toActionError(error));
    }
  }

  async function handleSubmitExercise() {
    if (
      !session ||
      !activeExercise ||
      !lastRun ||
      isStale ||
      lastRun.runtime_status === "unsupported" ||
      lastRunMode !== "visible_tests"
    ) {
      return;
    }
    setLastExerciseAction("submit");
    const materializedCode = materializeExerciseCode(editorCode, filledBlanks);
    setExerciseActionState({ status: "loading", label: "正在提交结果并写回知识点状态" });
    try {
      const response = await submitLearningExercise({
        sessionId: session.session_id,
        exerciseId: activeExercise.id,
        attemptId: lastRun.attempt_id,
        code: materializedCode,
        filledBlanks,
        submitVersion: 1,
        explanation: explanationText.trim() || undefined,
        hintUsageCount,
        errorCount,
      });
      startTransition(() => {
        onSubmitChange(response);
        onKnowledgePointUpdate(response.KnowledgePoint);
        setExerciseActionState({ status: "idle" });
        setIsStale(false);
      });
    } catch (error) {
      setExerciseActionState(toActionError(error));
    }
  }

  async function handleRequestHint() {
    if (!session || !activeExercise || !lastRun || isStale || !selectedBlankId) {
      return;
    }
    setLastExerciseAction("hint");
    setExerciseActionState({ status: "loading", label: "正在生成分层提示" });
    try {
      const response = await requestLearningHint({
        sessionId: session.session_id,
        exerciseId: activeExercise.id,
        attemptId: lastRun.attempt_id,
        currentCode: materializeExerciseCode(editorCode, filledBlanks),
        blankId: selectedBlankId,
        hintLevel,
      });
      startTransition(() => {
        setHintUsageCount((current) => Math.max(current, response.hint_usage_count));
        setHintHistory((current) => [response, ...current.filter((item) => item.hint.content !== response.hint.content)].slice(0, 4));
        setExerciseActionState({ status: "idle" });
      });
    } catch (error) {
      setExerciseActionState(toActionError(error));
    }
  }

  async function handleExplainError() {
    if (!session || !lastRun || isStale) {
      return;
    }
    const failedTests = lastRun.test_results
      .filter((item) => !item.passed)
      .map((item) => ({
        case_id: item.case_id,
        case_type: item.case_type,
        message: item.message,
      }));
    if (lastRun.runtime_status === "success" && failedTests.length === 0) {
      return;
    }
    setLastExerciseAction("explain_error");
    setExerciseActionState({ status: "loading", label: "正在解释真实错误上下文" });
    try {
      const response = await explainLearningError({
        sessionId: session.session_id,
        attemptId: lastRun.attempt_id,
        errorMessage: lastRun.error_message,
        stderr: lastRun.stderr,
        failedTests,
        currentCode: materializeExerciseCode(editorCode, filledBlanks),
      });
      startTransition(() => {
        setExplainErrorResult(response);
        setExerciseActionState({ status: "idle" });
      });
    } catch (error) {
      setExerciseActionState(toActionError(error));
    }
  }

  async function handleCheckExplanation() {
    if (!session || !lastRun || isStale || explanationText.trim().length === 0) {
      return;
    }
    setLastExerciseAction("check_explanation");
    setExerciseActionState({ status: "loading", label: "正在检查你对关键代码的解释" });
    try {
      const response = await checkLearningExplanation({
        sessionId: session.session_id,
        attemptId: lastRun.attempt_id,
        explanation: explanationText.trim(),
        focus: explanationFocus,
        round: explanationRound,
      });
      startTransition(() => {
        setExplanationCheckResult(response);
        setExerciseActionState({ status: "idle" });
        if (response.follow_up_required) {
          setExplanationRound((current) => Math.min(current + 1, 2));
        }
      });
    } catch (error) {
      setExerciseActionState(toActionError(error));
    }
  }

  function handleRetryExerciseAction() {
    if (lastExerciseAction === "run_preview") {
      void handleRunExercise("preview");
      return;
    }
    if (lastExerciseAction === "run_tests") {
      void handleRunExercise("visible_tests");
      return;
    }
    if (lastExerciseAction === "submit") {
      void handleSubmitExercise();
      return;
    }
    if (lastExerciseAction === "hint") {
      void handleRequestHint();
      return;
    }
    if (lastExerciseAction === "explain_error") {
      void handleExplainError();
      return;
    }
    if (lastExerciseAction === "check_explanation") {
      void handleCheckExplanation();
    }
  }

  return (
    <section className="conversation" aria-label="Agent 代码练习对话">
      <div className="thread">
        <div className="lesson-title">
          <p>{session ? `当前只解决一个问题：${session.context_snapshot.KnowledgePoint.title}。先运行，再根据测试结果决定下一步。` : "今天只解决一个问题：状态变量应该放在哪里，测试为什么会失败。"}</p>
        </div>

        <ThreadMessages messages={messages} />

        {sessionState.status === "loading" && <SystemCard title="系统状态" body="正在启动当前知识点会话…" />}
        {sessionState.status === "error" && (
          <SystemCard
            title="启动失败"
            body={sessionState.message}
            actionLabel="重试当前知识点"
            onAction={() => {
              if (createdPlan && sessionState.knowledgePointId) {
                void onOpenLearningSession(createdPlan, sessionState.knowledgePointId);
              }
            }}
          />
        )}

        {!session && sessionState.status === "idle" && (
          <SystemCard
            title="会话未开始"
            body="确认学习计划后，主页会在这里承载真实 M3 练习、运行反馈和提交结果。"
          />
        )}

        {session && activeExercise && (
          <>
            <article className="message agent">
              <div className="avatar">A</div>
              <div className="bubble">
                <div className="bubble-label">Agent</div>
                <p>{session.initial_agent_message}</p>
                <div className="tool-card">
                  当前练习：{activeExercise.title} · {session.context_snapshot.KnowledgePoint.title}
                </div>
              </div>
            </article>

            <ExerciseWorkbench
              session={session}
              exercise={activeExercise}
              code={editorCode}
              filledBlanks={filledBlanks}
              lastRun={lastRun}
              lastRunMode={lastRunMode}
              lastSubmit={lastSubmit}
              actionState={exerciseActionState}
              isStale={isStale}
              hintUsageCount={hintUsageCount}
              errorCount={errorCount}
              hintLevel={hintLevel}
              selectedBlankId={selectedBlankId}
              hintHistory={hintHistory}
              explainErrorResult={explainErrorResult}
              explanationText={explanationText}
              explanationFocus={explanationFocus}
              explanationRound={explanationRound}
              explanationCheckResult={explanationCheckResult}
              onCodeChange={(value) => {
                setEditorCode(value);
                if (lastRun || lastSubmit) {
                  setIsStale(true);
                }
              }}
              onBlankChange={(blankKey, value) => {
                setFilledBlanks((current) => ({ ...current, [blankKey]: value }));
                if (lastRun || lastSubmit) {
                  setIsStale(true);
                }
              }}
              onRunPreview={() => void handleRunExercise("preview")}
              onRunVisibleTests={() => void handleRunExercise("visible_tests")}
              onSubmit={() => void handleSubmitExercise()}
              onHintLevelChange={setHintLevel}
              onSelectedBlankChange={setSelectedBlankId}
              onRequestHint={() => void handleRequestHint()}
              onExplainError={() => void handleExplainError()}
              onExplanationTextChange={setExplanationText}
              onExplanationFocusChange={setExplanationFocus}
              onCheckExplanation={() => void handleCheckExplanation()}
              onRetryAction={handleRetryExerciseAction}
              onOpenNoteDrawer={onOpenNoteDrawer}
            />
          </>
        )}
      </div>
    </section>
  );
}
