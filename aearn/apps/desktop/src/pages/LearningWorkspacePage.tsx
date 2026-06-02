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
import { AssistantUIThread } from "../components/AssistantUIThread";
import {
  LearningToolRuntimeProvider,
} from "../components/generative-ui/assistantToolUIs";
import type { CodeExerciseToolArgs, ConceptChoiceOption } from "../components/generative-ui/types";
import { SystemCard } from "../components/SystemCard";
import { ExerciseWorkbench } from "../features/learning/ExerciseWorkbench";
import {
  buildRunAgentFeedback,
  buildSubmitAgentFeedback,
  createMessage,
  initialBlankState,
  materializeExerciseCode,
  toActionError,
} from "../lib/learningHelpers";
import { useSSE } from "../hooks/useSSE";
import type { SSEToolCall } from "../hooks/useSSE";
import type {
  CreatedPlanResponse,
  ExplainErrorResponse,
  ExplanationCheckResponse,
  ExplanationFocus,
  HintLevel,
  HintResponse,
  LearningExercise,
  RunExerciseResponse,
  SubmitExerciseResponse,
  UserProfile,
} from "../types";

type ComposerStreamRequest = {
  endpoint: string;
  requestId: string;
  assistantMessageId: string;
  body: {
    user_id: string;
    role: "user";
    content: string;
    client_message_id: string;
  };
};

type LearningWorkspacePageProps = {
  user: UserProfile | null;
  createdPlan: CreatedPlanResponse | null;
  sessionState: SessionState;
  messages: ConversationMessage[];
  lastRun: RunExerciseResponse | null;
  lastSubmit: SubmitExerciseResponse | null;
  resetNonce: number;
  canOpenNoteDrawer: boolean;
  noteDrawerOpen: boolean;
  onOpenLearningSession: (planResponse: CreatedPlanResponse, knowledgePointId: string) => Promise<void> | void;
  onReturnToRoute: () => void;
  onRunChange: (run: RunExerciseResponse | null) => void;
  onSubmitChange: (submit: SubmitExerciseResponse | null) => void;
  onKnowledgePointUpdate: (patch: SubmitExerciseResponse["KnowledgePoint"]) => void;
  onOpenNoteDrawer: () => void;
  onCloseNoteDrawer: () => void;
  onAddMessage: (msg: ConversationMessage) => void;
  onUpdateMessage: (id: string, patch: { text?: string; appendText?: string; status?: ConversationMessage["status"]; statusText?: string }) => void;
  onStartToolCall: (messageId: string, toolCallId: string, name: string) => void;
  onAppendToolCallDelta: (messageId: string, toolCallId: string, delta: string) => void;
  onFinalizeToolCall: (messageId: string, toolCallId: string, args: unknown) => void;
};

export function LearningWorkspacePage({
  user,
  createdPlan,
  sessionState,
  messages,
  lastRun,
  lastSubmit,
  resetNonce,
  canOpenNoteDrawer,
  noteDrawerOpen,
  onOpenLearningSession,
  onReturnToRoute,
  onRunChange,
  onSubmitChange,
  onKnowledgePointUpdate,
  onOpenNoteDrawer,
  onCloseNoteDrawer,
  onAddMessage,
  onUpdateMessage,
  onStartToolCall,
  onAppendToolCallDelta,
  onFinalizeToolCall,
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
  const [composerStream, setComposerStream] = useState<ComposerStreamRequest | null>(null);
  const [unlockedExercise, setUnlockedExercise] = useState<LearningExercise | null>(null);
  const conversationScrollRef = useRef<HTMLElement | null>(null);

  const session = sessionState.status === "ready" ? sessionState.data : null;
  const activeExercise = session?.exercise ?? unlockedExercise;
  const initialAgentMessage = session?.initial_agent_message.trim() ?? "";
  const initialToolCalls = session?.initial_tool_calls ?? [];
  const composerStreaming = composerStream !== null;
  const hasExerciseToolMessage = messages.some((message) =>
    message.toolCalls?.some((toolCall) => toolCall.name === "show_code_exercise"),
  );
  const practiceUnlocked = session?.learning_stage === "practice_support" || Boolean(activeExercise) || hasExerciseToolMessage;
  const resumeExerciseMessage: ConversationMessage | null =
    session && session.exercise && !hasExerciseToolMessage
      ? {
          id: `resume-exercise-${session.session_id}-${session.exercise.id}`,
          speaker: "agent",
          text: "",
          label: "Agent",
          status: "done",
          toolCalls: [
            {
              id: `tc_resume_${session.exercise.id}`,
              name: "show_code_exercise",
              args: {
                session_id: session.session_id,
                knowledge_point_id: session.context_snapshot.KnowledgePoint.id,
                exercise: session.exercise,
                unlock_reason: session.learning_stage_state.practice_unlock_reason ?? "legacy_session",
                learning_incomplete: Boolean(session.learning_stage_state.learning_incomplete),
                concept_summary: session.learning_stage_state.concept_summary ?? "",
                notice: session.learning_stage_state.learning_incomplete
                  ? `当前学习进度尚未完成。概念小结：${session.learning_stage_state.concept_summary ?? ""}`
                  : `概念小结：${session.learning_stage_state.concept_summary ?? ""}`,
              },
              argsBuffer: "",
              status: "done",
            },
          ],
        }
      : null;

  const initialMessage: ConversationMessage | null =
    session && (initialAgentMessage || initialToolCalls.length > 0)
      ? {
          id: `initial-${session.session_id}`,
          speaker: "agent" as const,
          text: initialAgentMessage,
          label: "Agent",
          status: "done" as const,
          toolCalls: initialToolCalls.map((toolCall) => ({
            id: toolCall.id,
            name: toolCall.name,
            args: toolCall.args,
            argsBuffer: "",
            status: toolCall.status === "done" ? "done" : "pending",
          })),
        }
      : null;

  const threadMessages: ConversationMessage[] = initialMessage
    ? [
        initialMessage,
        ...messages,
        ...(resumeExerciseMessage ? [resumeExerciseMessage] : []),
      ]
    : [...messages, ...(resumeExerciseMessage ? [resumeExerciseMessage] : [])];

  const learningQuickReplies = practiceUnlocked
    ? ["给我提示", "解释这个错误"]
    : quickRepliesForConceptCheck(threadMessages);

  // --- SSE streaming for composer messages ---
  useSSE(composerStream?.endpoint ?? null, {
    method: "POST",
    body: composerStream?.body,
    requestId: composerStream?.requestId,
    onEvent: (streamEvent) => {
      if (!composerStream) return;
      if (streamEvent.type === "agent_message") {
        const incomingText = streamEvent.data.content || streamEvent.data.delta;
        onUpdateMessage(composerStream.assistantMessageId, {
          text: streamEvent.data.content ? incomingText : undefined,
          appendText: streamEvent.data.content ? undefined : incomingText,
          status: "streaming",
          statusText: "正在生成……",
        });
      }
      if (streamEvent.type === "tool_call") {
        handleToolCallEvent(composerStream.assistantMessageId, streamEvent.data);
      }
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

  function handleComposerSubmit(input: string) {
    const content = input.trim();
    if (content.length === 0 || composerStreaming || !session || !user) return;

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
        user_id: user.id,
        role: "user",
        content,
        client_message_id: createClientId("desktop_msg"),
      },
    });
  }

  function handleToolCallEvent(messageId: string, payload: SSEToolCall) {
    if (payload.phase === "start") {
      onStartToolCall(messageId, payload.tool_call_id, payload.name);
      return;
    }
    if (payload.phase === "delta") {
      onAppendToolCallDelta(messageId, payload.tool_call_id, payload.arguments_delta);
      return;
    }
    if (payload.phase === "done") {
      const exercise = extractExerciseFromToolArgs(payload.arguments);
      if (exercise) {
        setUnlockedExercise(exercise);
      }
      onFinalizeToolCall(messageId, payload.tool_call_id, payload.arguments);
    }
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
    setUnlockedExercise(session?.exercise ?? null);
  }, [session?.session_id, session?.exercise?.id, resetNonce]);

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
    if (!session || !activeExercise || !user) {
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
        userId: user.id,
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
        onAddMessage(createMessage("agent", buildRunAgentFeedback(response, runMode), "Agent"));
      });
    } catch (error) {
      setExerciseActionState(toActionError(error));
    }
  }

  async function handleSubmitExercise() {
    if (
      !session ||
      !activeExercise ||
      !user ||
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
        userId: user.id,
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
        onAddMessage(createMessage("agent", buildSubmitAgentFeedback(response), "Agent"));
      });
    } catch (error) {
      setExerciseActionState(toActionError(error));
    }
  }

  async function handleRequestHint() {
    if (!session || !activeExercise || !user || !lastRun || isStale || !selectedBlankId) {
      return;
    }
    setLastExerciseAction("hint");
    setExerciseActionState({ status: "loading", label: "正在生成分层提示" });
    try {
      const response = await requestLearningHint({
        userId: user.id,
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
    if (!session || !user || !lastRun || isStale) {
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
        userId: user.id,
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
    if (!session || !user || !lastRun || isStale || explanationText.trim().length === 0) {
      return;
    }
    setLastExerciseAction("check_explanation");
    setExerciseActionState({ status: "loading", label: "正在检查你对关键代码的解释" });
    try {
      const response = await checkLearningExplanation({
        userId: user.id,
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

  function renderCodeExerciseTool(args: CodeExerciseToolArgs | null) {
    if (!session || !args) {
      return <div className="tool-card">正在准备练习卡片…</div>;
    }
    const exercise = activeExercise ?? args.exercise;
    return (
      <div className="learning-tool-exercise">
        {args.notice && <div className="draft-boundary early-practice-notice">{args.notice}</div>}
        <ExerciseWorkbench
          session={session}
          exercise={exercise}
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
      </div>
    );
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

          <LearningToolRuntimeProvider runtime={{ renderCodeExercise: renderCodeExerciseTool }}>
            <AssistantUIThread
              messages={session ? threadMessages : []}
              isStreaming={composerStreaming}
              sessionActive={Boolean(session)}
              onSend={handleComposerSubmit}
              emptyState={!session && sessionState.status === "idle" ? emptyState : undefined}
              placeholder={
                composerStreaming
                  ? "AI 正在回复……"
                  : !session
                    ? "先从左侧路线进入一个知识点，再向 Agent 追问。"
                    : practiceUnlocked
                      ? "粘贴你的代码、运行输出、测试失败或请 Agent 解释错因……"
                      : "先追问概念、尝试费曼复述，或输入“开始练习”提前进入练习……"
              }
              guidanceText={!session ? "先进入一个 active learning session，composer 才会调用模型流式回答。" : undefined}
              canOpenNoteDrawer={canOpenNoteDrawer}
              noteDrawerOpen={noteDrawerOpen}
              onToggleNoteDrawer={() => {
                noteDrawerOpen ? onCloseNoteDrawer() : onOpenNoteDrawer();
              }}
              hideNoteButton={false}
              quickReplies={session ? learningQuickReplies : undefined}
            />
          </LearningToolRuntimeProvider>

          {sessionState.status === "loading" && <SystemCard title="系统状态" body="正在启动当前知识点会话…" />}
          {sessionState.status === "error" && (
            <article className="system-card concept-start-error">
              <h3>启动失败</h3>
              <p>{sessionState.message}</p>
              <div className="system-card-actions">
                <button
                  className="btn primary ghost-btn"
                  type="button"
                  onClick={() => {
                    if (createdPlan && sessionState.knowledgePointId) {
                      void onOpenLearningSession(createdPlan, sessionState.knowledgePointId);
                    }
                  }}
                >
                  重试生成
                </button>
                <button className="btn ghost-btn" type="button" onClick={onReturnToRoute}>
                  返回路线
                </button>
              </div>
            </article>
          )}

        </div>
      </section>
    </div>
  );
}

function createClientId(prefix: string): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  return uuid ? `${prefix}_${uuid}` : `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function extractExerciseFromToolArgs(args: unknown): LearningExercise | null {
  if (typeof args !== "object" || args === null || !("exercise" in args)) {
    return null;
  }
  const exercise = (args as { exercise?: unknown }).exercise;
  if (typeof exercise !== "object" || exercise === null || !("id" in exercise)) {
    return null;
  }
  return exercise as LearningExercise;
}

function quickRepliesForConceptCheck(messages: ConversationMessage[]): string[] {
  return latestConceptQuickReplies(messages) ?? ["我不确定", "开始练习"];
}

function latestConceptQuickReplies(messages: ConversationMessage[]): string[] | null {
  for (let messageIndex = messages.length - 1; messageIndex >= 0; messageIndex -= 1) {
    const toolCalls = messages[messageIndex].toolCalls ?? [];
    for (let toolIndex = toolCalls.length - 1; toolIndex >= 0; toolIndex -= 1) {
      const toolCall = toolCalls[toolIndex];
      if (toolCall.name === "show_concept_check_result") {
        const repairOptions = conceptOptionsFromPath(toolCall.args, ["repair_check", "options"]);
        if (repairOptions.length > 0) {
          return repairOptions.map((option) => option.id);
        }
        const actionLabels = conceptActionLabels(toolCall.args);
        if (actionLabels.length > 0) {
          return actionLabels;
        }
      }
      if (toolCall.name === "show_concept_intro") {
        const introOptions = conceptOptionsFromPath(toolCall.args, ["check", "options"]);
        if (introOptions.length > 0) {
          return introOptions.map((option) => option.id);
        }
      }
      if (toolCall.name === "show_code_exercise") {
        return null;
      }
    }
  }
  return null;
}

function conceptOptionsFromPath(value: unknown, path: string[]): ConceptChoiceOption[] {
  let current = value;
  for (const key of path) {
    if (!isRecord(current)) {
      return [];
    }
    current = current[key];
  }
  if (!Array.isArray(current)) {
    return [];
  }
  return current
    .filter((option): option is Record<string, unknown> => isRecord(option))
    .map((option, index) => ({
      id: typeof option.id === "string" && option.id.trim() ? option.id.trim() : String.fromCharCode(65 + index),
      text: typeof option.text === "string" ? option.text : "",
    }))
    .filter((option) => option.text.trim().length > 0);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function conceptActionLabels(value: unknown): string[] {
  if (!isRecord(value) || !Array.isArray(value.actions)) {
    return [];
  }
  return value.actions
    .filter((action): action is Record<string, unknown> => isRecord(action))
    .map((action) => (typeof action.label === "string" ? action.label.trim() : ""))
    .filter(Boolean);
}
