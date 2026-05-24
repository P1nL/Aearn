import { startTransition, useEffect, useRef, useState } from "react";

import {
  buildLearningMessageSSEUrl,
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
import { AssistantThread } from "../components/AssistantThread";
import { LearningComposer } from "../components/LearningComposer";
import { SystemCard } from "../components/SystemCard";
import { ExerciseWorkbench } from "../features/learning/ExerciseWorkbench";
import {
  createMessage,
  initialBlankState,
  materializeExerciseCode,
  toActionError,
} from "../lib/learningHelpers";
import { useSSE } from "../hooks/useSSE";
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

type ComposerStreamRequest = {
  endpoint: string;
  requestId: string;
  assistantMessageId: string;
  body: {
    role: "user";
    content: string;
    client_message_id: string;
  };
};

type LearningWorkspacePageProps = {
  createdPlan: CreatedPlanResponse | null;
  sessionState: SessionState;
  messages: ConversationMessage[];
  lastRun: RunExerciseResponse | null;
  lastSubmit: SubmitExerciseResponse | null;
  resetNonce: number;
  canOpenNoteDrawer: boolean;
  noteDrawerOpen: boolean;
  onOpenLearningSession: (planResponse: CreatedPlanResponse, knowledgePointId: string) => Promise<void> | void;
  onRunChange: (run: RunExerciseResponse | null) => void;
  onSubmitChange: (submit: SubmitExerciseResponse | null) => void;
  onKnowledgePointUpdate: (patch: SubmitExerciseResponse["KnowledgePoint"]) => void;
  onOpenNoteDrawer: () => void;
  onCloseNoteDrawer: () => void;
  onAddMessage: (msg: ConversationMessage) => void;
  onUpdateMessage: (id: string, patch: { text?: string; appendText?: string; status?: ConversationMessage["status"]; statusText?: string }) => void;
};

export function LearningWorkspacePage({
  createdPlan,
  sessionState,
  messages,
  lastRun,
  lastSubmit,
  resetNonce,
  canOpenNoteDrawer,
  noteDrawerOpen,
  onOpenLearningSession,
  onRunChange,
  onSubmitChange,
  onKnowledgePointUpdate,
  onOpenNoteDrawer,
  onCloseNoteDrawer,
  onAddMessage,
  onUpdateMessage,
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
  const [composerInput, setComposerInput] = useState("");
  const [composerStream, setComposerStream] = useState<ComposerStreamRequest | null>(null);
  const conversationScrollRef = useRef<HTMLElement | null>(null);

  const session = sessionState.status === "ready" ? sessionState.data : null;
  const activeExercise = session?.exercise ?? null;
  const initialAgentMessage = session?.initial_agent_message.trim() ?? "";
  const composerStreaming = composerStream !== null;

  // Build thread messages with initialAgentMessage prepended as a proper message
  const threadMessages: ConversationMessage[] = session && initialAgentMessage
    ? [
        {
          id: `initial-${session.session_id}`,
          speaker: "agent" as const,
          text: initialAgentMessage,
          label: "Agent",
          toolCard: activeExercise ? `当前练习：${activeExercise.title} · ${session.context_snapshot.KnowledgePoint.title}` : undefined,
          status: "done" as const,
        },
        ...messages,
      ]
    : messages;

  const LEARNING_QUICK_REPLIES = ["给我提示", "解释这个错误"];

  // --- SSE streaming for composer messages ---
  useSSE(composerStream?.endpoint ?? null, {
    method: "POST",
    body: composerStream?.body,
    requestId: composerStream?.requestId,
    onEvent: (streamEvent) => {
      if (!composerStream || streamEvent.type !== "agent_message") return;
      const incomingText = streamEvent.data.content || streamEvent.data.delta;
      onUpdateMessage(composerStream.assistantMessageId, {
        text: streamEvent.data.content ? incomingText : undefined,
        appendText: streamEvent.data.content ? undefined : incomingText,
        status: "streaming",
        statusText: "正在生成……",
      });
    },
    onDone: () => {
      if (!composerStream) return;
      onUpdateMessage(composerStream.assistantMessageId, {
        status: "done",
        statusText: undefined,
      });
      setComposerStream(null);
    },
    onError: (error) => {
      if (!composerStream) return;
      onUpdateMessage(composerStream.assistantMessageId, {
        text: `这次回答没有完成：${error.code}。${error.message}`,
        status: "error",
        statusText: "可以修改问题后重试。",
      });
      setComposerStream(null);
    },
  });

  function handleComposerSubmit() {
    const content = composerInput.trim();
    if (content.length === 0 || composerStreaming || !session) return;

    const assistantMessage: ConversationMessage = {
      ...createMessage("agent", "", "Agent"),
      status: "streaming",
      statusText: "正在连接模型……",
    };
    onAddMessage(createMessage("user", content));
    onAddMessage(assistantMessage);
    setComposerStream({
      endpoint: buildLearningMessageSSEUrl(session.session_id),
      requestId: createClientId("desktop_req"),
      assistantMessageId: assistantMessage.id,
      body: {
        role: "user",
        content,
        client_message_id: createClientId("desktop_msg"),
      },
    });
    setComposerInput("");
  }

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

  useEffect(() => {
    const scrollContainer = conversationScrollRef.current;
    if (!scrollContainer) return;
    const frame = window.requestAnimationFrame(() => {
      scrollContainer.scrollTop = scrollContainer.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [messages.length, session?.session_id, activeExercise?.id, exerciseActionState.status, lastRun?.attempt_id, lastSubmit?.attempt_id]);

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

  const emptyState = (
    <div className="empty-chat-state">
      <span className="empty-chat-kicker">Aearn Dialogue</span>
      <h1>{createdPlan ? "选择知识点后开始对话" : "生成路线后开始真实对话"}</h1>
      <p>
        {createdPlan
          ? "左侧会展示由你的学习目标生成的模块和知识点。进入知识点后，底部输入框会连接当前 learning session 的流式 Agent。"
          : "对话区默认保持空白，不再用原型里的固定示例填充。"}
      </p>
    </div>
  );

  return (
    <div className="learning-workspace-layout">
      <section className="conversation" aria-label="Agent 代码练习对话" ref={conversationScrollRef}>
        <div className="thread">
          <div className="lesson-title">
            <p>
              {session
                ? `当前知识点：${session.context_snapshot.KnowledgePoint.title}。对话、运行结果和练习反馈会留在同一个线程里。`
                : createdPlan
                  ? "从左侧学习路线选择一个知识点，主区会打开真实会话并启用 Agent 对话。"
                  : "先完成建档生成学习路线；这里不会预置固定示例对话。"}
            </p>
          </div>

          {!session && sessionState.status === "idle" && (
            <AssistantThread messages={[]} emptyState={emptyState} />
          )}

          {session && <AssistantThread messages={threadMessages} />}

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

          {session && activeExercise && (
            <>

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

      <LearningComposer
        value={composerInput}
        onChange={setComposerInput}
        onSubmit={handleComposerSubmit}
        disabled={composerStreaming}
        streaming={composerStreaming}
        sessionActive={Boolean(session)}
        canOpenNoteDrawer={canOpenNoteDrawer}
        noteDrawerOpen={noteDrawerOpen}
        onToggleNoteDrawer={() => { noteDrawerOpen ? onCloseNoteDrawer() : onOpenNoteDrawer(); }}
        quickReplies={session && messages.length === 0 ? LEARNING_QUICK_REPLIES : undefined}
      />
    </div>
  );
}

function createClientId(prefix: string): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  return uuid ? `${prefix}_${uuid}` : `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}
