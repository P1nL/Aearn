import { startTransition, useEffect, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import { buildReviewMessageSSEUrl, fetchReviewMessages, fetchTodayReviews, startReviewSession, submitReviewExerciseResult, submitReviewWarmupResult } from "../api";
import type { ConversationMessage, NoteContext } from "../appTypes";
import { AssistantUIThread } from "../components/AssistantUIThread";
import { CodeEditor } from "../features/learning/CodeEditor";
import { useSSE } from "../hooks/useSSE";
import { completionResultLabel, fsrsRatingLabel, runtimeLabel } from "../lib/desktopLabels";
import { formatErrorMessage } from "../lib/errorMessages";
import { createMessage } from "../lib/learningHelpers";
import { useAppStore } from "../stores/useAppStore";
import type {
  ReviewDueItem,
  ReviewHistoryMessage,
  ReviewAiPatchAnswer,
  ReviewExerciseResultResponse,
  ReviewSessionResponse,
  ReviewWarmupResultResponse,
  UserProfile,
} from "../types";

type ReviewPageProps = {
  isActive: boolean;
  user: UserProfile | null;
  selectedKnowledgePointId: string | null;
  messages: ConversationMessage[];
  onActiveKnowledgePointChange: (knowledgePointId: string | null) => void;
  onActiveNoteContextChange: (context: NoteContext | null) => void;
};

type ReviewStreamRequest = {
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

const REVIEW_QUICK_REPLIES = ["我记得", "不太确定", "完全忘了"];

export function ReviewPage({
  isActive,
  user,
  selectedKnowledgePointId,
  messages,
  onActiveKnowledgePointChange,
  onActiveNoteContextChange,
}: ReviewPageProps) {
  const store = useAppStore();
  const [dueItems, setDueItems] = useState<ReviewDueItem[]>([]);
  const [loadState, setLoadState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [activeReview, setActiveReview] = useState<ReviewSessionResponse | null>(null);
  const [editorCode, setEditorCode] = useState("");
  const [filledBlanks, setFilledBlanks] = useState<Record<string, string>>({});
  const [explanation, setExplanation] = useState("");
  const [warmupAnswer, setWarmupAnswer] = useState("");
  const [warmupState, setWarmupState] = useState<"idle" | "submitting" | "error">("idle");
  const [startingKnowledgePointId, setStartingKnowledgePointId] = useState<string | null>(null);
  const [startRequestedKnowledgePointId, setStartRequestedKnowledgePointId] = useState<string | null>(null);
  const [reviewPatchAnswer, setReviewPatchAnswer] = useState<ReviewAiPatchAnswer>({
    verdict: "fail",
    evidence: "",
    knowledge_point_risk: "",
    next_action: "request_change",
  });
  const [submitState, setSubmitState] = useState<"idle" | "submitting" | "done" | "error">("idle");
  const [reviewResult, setReviewResult] = useState<ReviewExerciseResultResponse | null>(null);
  const [streamRequest, setStreamRequest] = useState<ReviewStreamRequest | null>(null);
  const conversationScrollRef = useRef<HTMLElement | null>(null);

  const isStreaming = streamRequest !== null;

  // SSE streaming for review messages
  useSSE(streamRequest?.endpoint ?? null, {
    method: "POST",
    body: streamRequest?.body,
    requestId: streamRequest?.requestId,
    onEvent: (streamEvent) => {
      if (!streamRequest || streamEvent.type !== "agent_message") return;
      const incomingText = streamEvent.data.content || streamEvent.data.delta;
      store.updateReviewMessage(streamRequest.assistantMessageId, {
        text: streamEvent.data.content ? incomingText : undefined,
        appendText: streamEvent.data.content ? undefined : incomingText,
        status: "streaming",
        statusText: "正在生成……",
      });
    },
    onDone: () => {
      if (!streamRequest) return;
      store.updateReviewMessage(streamRequest.assistantMessageId, {
        status: "done",
        statusText: undefined,
      });
      setStreamRequest(null);
    },
    onError: (error) => {
      if (!streamRequest) return;
      store.updateReviewMessage(streamRequest.assistantMessageId, {
        text: `回复出错：${error.code}。${error.message}`,
        status: "error",
        statusText: "可以修改问题后重试。",
      });
      setStreamRequest(null);
    },
  });

  // Auto-scroll on new messages
  useEffect(() => {
    const scrollContainer = conversationScrollRef.current;
    if (!scrollContainer) return;
    const frame = window.requestAnimationFrame(() => {
      scrollContainer.scrollTop = scrollContainer.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [messages.length, activeReview?.session_id, reviewResult?.attempt_id]);

  function handleComposerSubmit(input: string) {
    const content = input.trim();
    if (content.length === 0 || isStreaming || warmupState === "submitting" || !activeReview || !user) return;

    if (warmupPending) {
      store.addReviewMessage(createMessage("user", content));
      void handleWarmupSubmit(isWarmupSkipIntent(content) ? "skip" : "answer", content);
      return;
    }

    const assistantMessage: ConversationMessage = {
      ...createMessage("agent", "", "Agent"),
      status: "streaming",
      statusText: "正在连接模型……",
    };

    store.addReviewMessage(createMessage("user", content));
    store.addReviewMessage(assistantMessage);

    setStreamRequest({
      endpoint: buildReviewMessageSSEUrl(activeReview.session_id),
      requestId: createClientId("desktop_review_req"),
      assistantMessageId: assistantMessage.id,
      body: {
        user_id: user.id,
        role: "user",
        content,
        client_message_id: createClientId("desktop_review_msg"),
      },
    });
  }

  async function loadDueReviews(signal?: AbortSignal) {
    if (!user) {
      setDueItems([]);
      setLoadState("idle");
      return;
    }
    setLoadState("loading");
    setErrorMessage(null);
    try {
      const response = await fetchTodayReviews(user.id, signal);
      startTransition(() => {
        setDueItems(response.items);
        setLoadState("ready");
      });
    } catch (error) {
      if (signal?.aborted) {
        return;
      }
      setLoadState("error");
      setErrorMessage(formatErrorMessage(error, "无法加载今日复习"));
    }
  }

  async function handleStartReview(item: ReviewDueItem) {
    if (!user) {
      return;
    }
    if (activeReview?.knowledge_point.id !== item.KnowledgePoint.id) {
      setActiveReview(null);
      store.clearReviewConversation();
    }
    setStartingKnowledgePointId(item.KnowledgePoint.id);
    setSubmitState("idle");
    setWarmupState("idle");
    setReviewResult(null);
    setErrorMessage(null);
    try {
      const response = await startReviewSession({
        userId: user.id,
        knowledgePointId: item.KnowledgePoint.id,
      });
      const restoredMessages = await restoreReviewConversationMessages({
        userId: user.id,
        sessionId: response.session_id,
        fallbackReview: response,
      });
      startTransition(() => {
        setActiveReview(response);
        setEditorCode(response.review_exercise.starter_code);
        setFilledBlanks(defaultFilledBlanks(response));
        setExplanation("");
        setWarmupAnswer(response.warmup.last_answer ?? "");
        setReviewPatchAnswer(defaultReviewPatchAnswer());
      });
      onActiveKnowledgePointChange(response.knowledge_point.id);
      store.setReviewConversation(restoredMessages);
    } catch (error) {
      setErrorMessage(formatErrorMessage(error, "无法开始复习"));
    } finally {
      setStartingKnowledgePointId(null);
    }
  }

  async function handleWarmupSubmit(action: "answer" | "skip", answerOverride?: string) {
    if (!activeReview || !user || warmupState === "submitting") {
      return;
    }
    const submittedAnswer = answerOverride ?? warmupAnswer;
    setWarmupState("submitting");
    setErrorMessage(null);
    try {
      const response = await submitReviewWarmupResult({
        userId: user.id,
        sessionId: activeReview.session_id,
        action,
        answer: action === "skip" ? undefined : submittedAnswer,
      });
      startTransition(() => {
        setActiveReview((current) =>
          current
            ? {
                ...current,
                review_stage: response.review_stage,
                review_stage_state: response.review_stage_state,
                current_node: response.current_node,
                warmup: response.warmup,
              }
            : current,
        );
        setWarmupAnswer(response.warmup.last_answer ?? submittedAnswer);
        setWarmupState("idle");
      });
      store.addReviewMessage(createMessage("agent", buildWarmupResultMessage(response), "Agent"));
    } catch (error) {
      setWarmupState("error");
      setErrorMessage(formatErrorMessage(error, "热身提交失败"));
    }
  }

  async function handleSubmitReview() {
    if (!activeReview || !user || submitState === "submitting") {
      return;
    }
    setSubmitState("submitting");
    setErrorMessage(null);
    try {
      const exercise = activeReview.review_exercise;
      const result = await submitReviewExerciseResult({
        userId: user.id,
        sessionId: activeReview.session_id,
        exerciseId: exercise.id,
        code: exercise.exercise_type === "review_ai_patch" ? editorCode || patchOriginalCode(exercise.metadata_json) : buildSubmittedCode(editorCode, filledBlanks),
        filledBlanks: exercise.exercise_type === "review_ai_patch" ? {} : filledBlanks,
        explanation: exercise.exercise_type === "review_ai_patch" ? reviewPatchAnswer.evidence : explanation,
        reviewAiPatchAnswer: exercise.exercise_type === "review_ai_patch" ? reviewPatchAnswer : undefined,
      });
      startTransition(() => {
        setReviewResult(result);
        setActiveReview((current) =>
          current
            ? {
                ...current,
                review_stage: "submitted",
                ReviewState: result.ReviewState,
                knowledge_point: {
                  ...current.knowledge_point,
                  status: result.KnowledgePoint.status,
                },
              }
            : current,
        );
        setSubmitState("done");
      });
      // Add AI feedback as a message in the thread
      store.addReviewMessage(
        createMessage("agent", result.feedback, "Agent"),
      );
      await loadDueReviews();
    } catch (error) {
      setSubmitState("error");
      setErrorMessage(formatErrorMessage(error, "复习提交失败"));
    }
  }

  useEffect(() => {
    if (!isActive) {
      onActiveNoteContextChange(null);
      return;
    }
    const controller = new AbortController();
    void loadDueReviews(controller.signal);
    return () => controller.abort();
  }, [isActive, user?.id]);

  useEffect(() => {
    if (!isActive) {
      return;
    }
    setErrorMessage(null);
    setReviewResult(null);
    setStartRequestedKnowledgePointId(null);
    if (!selectedKnowledgePointId) {
      setActiveReview(null);
      store.clearReviewConversation();
      onActiveNoteContextChange(null);
    }
  }, [isActive, selectedKnowledgePointId, user?.id]);

  useEffect(() => {
    if (!isActive || !user || !selectedKnowledgePointId || loadState !== "ready" || startingKnowledgePointId) {
      return;
    }
    if (activeReview?.knowledge_point.id === selectedKnowledgePointId) {
      return;
    }
    if (startRequestedKnowledgePointId === selectedKnowledgePointId) {
      return;
    }

    const targetItem = dueItems.find((item) => item.KnowledgePoint.id === selectedKnowledgePointId);
    if (!targetItem) {
      setErrorMessage("这个知识点当前没有到期复习项；请从左侧选择标记为已到期的复习知识点。");
      return;
    }

    setStartRequestedKnowledgePointId(selectedKnowledgePointId);
    void handleStartReview(targetItem);
  }, [
    activeReview?.knowledge_point.id,
    dueItems,
    isActive,
    loadState,
    selectedKnowledgePointId,
    startRequestedKnowledgePointId,
    startingKnowledgePointId,
    user?.id,
  ]);

  useEffect(() => {
    if (!isActive || !activeReview) {
      onActiveNoteContextChange(null);
      return;
    }
    onActiveNoteContextChange({
      knowledgePointId: activeReview.knowledge_point.id,
      knowledgePointTitle: activeReview.knowledge_point.title,
      source: "review",
      sessionId: activeReview.session_id,
      language: activeReview.review_exercise.runtime_profile.language,
    });
  }, [isActive, activeReview?.session_id, activeReview?.knowledge_point.id]);

  const activeExercise = activeReview?.review_exercise ?? null;
  const warmupPending = activeReview?.review_stage === "warmup" || activeReview?.review_stage === "warmup_repair";
  const patchAnswerComplete =
    activeExercise?.exercise_type !== "review_ai_patch" ||
    (reviewPatchAnswer.evidence.trim().length > 0 && reviewPatchAnswer.knowledge_point_risk.trim().length > 0);
  const submitDisabled = !activeReview || warmupPending || !patchAnswerComplete || submitState === "submitting" || submitState === "done";
  const composerSessionActive = Boolean(activeReview);
  const composerBusy = isStreaming || warmupState === "submitting";
  const selectedDueItem = selectedKnowledgePointId ? dueItems.find((item) => item.KnowledgePoint.id === selectedKnowledgePointId) ?? null : null;
  const reviewThreadMessages = activeReview ? messages : [];
  const showReviewLoading =
    !activeReview && !errorMessage && (loadState === "loading" || startingKnowledgePointId !== null || selectedKnowledgePointId !== null);
  const showReviewStatus =
    !activeReview &&
    !showReviewLoading &&
    (!user || loadState === "error" || (loadState === "ready" && dueItems.length === 0) || Boolean(errorMessage));
  const reviewExerciseNode = activeReview ? (
    <>
      {errorMessage && <div className="tool-card">错误：{errorMessage}</div>}

      {activeExercise && !warmupPending && (
        <ReviewExerciseWorkbench
          review={activeReview}
          result={reviewResult}
          editorCode={editorCode}
          filledBlanks={filledBlanks}
          explanation={explanation}
          patchAnswer={reviewPatchAnswer}
          submitDisabled={submitDisabled}
          submitState={submitState}
          onCodeChange={setEditorCode}
          onBlankChange={(blankKey, value) =>
            setFilledBlanks((current) => ({
              ...current,
              [blankKey]: value,
            }))
          }
          onExplanationChange={setExplanation}
          onPatchAnswerChange={setReviewPatchAnswer}
          onSubmit={() => void handleSubmitReview()}
        />
      )}
    </>
  ) : null;

  return (
    <div className="review-screen">
      <div className="review-thread-wrap">
        <section className="conversation" aria-label="复习对话" ref={conversationScrollRef}>
          <div className="thread">
            {activeReview && (
              <>
                <div className="lesson-title">
                  <p>{`当前复习知识点：${activeReview.knowledge_point.title}。热身、变体练习和反馈会留在同一个线程里。`}</p>
                </div>

                <AssistantUIThread
                  messages={reviewThreadMessages}
                  isStreaming={composerBusy}
                  sessionActive={composerSessionActive}
                  onSend={handleComposerSubmit}
                  hideNoteButton
                  quickReplies={composerSessionActive && warmupPending ? REVIEW_QUICK_REPLIES : undefined}
                  placeholder={
                    composerBusy
                      ? warmupState === "submitting" ? "正在记录热身……" : "AI 正在回复……"
                      : warmupPending
                        ? "直接回答热身问题，或输入“跳过”。"
                        : "用自己的话复述，或请求提示……"
                  }
                  ariaLabel="复习输入框"
                  beforeComposer={reviewExerciseNode}
                />
              </>
            )}

            {showReviewLoading && (
              <div className="review-loading-state" role="status" aria-label="正在加载复习会话">
                <div className="wb-spinner" aria-hidden="true" />
              </div>
            )}

            {showReviewStatus && (
              <article className="system-card" aria-label="复习状态">
                <h3>复习状态</h3>
                <p>
                  {!user
                    ? "先完成建档和学习计划后，复习页才会加载待复习内容。"
                    : loadState === "ready" && dueItems.length === 0
                        ? "当前没有已到期复习项。"
                        : errorMessage ?? "等待你从左侧选择一个已到期复习知识点。"}
                </p>
                {(errorMessage || (user && loadState === "ready" && dueItems.length === 0)) && (
                  <div className="system-card-actions">
                    <button className="btn ghost-btn" type="button" disabled={!user || loadState === "loading"} onClick={() => void loadDueReviews()}>
                      {loadState === "loading" ? "刷新中..." : "重新加载复习状态"}
                    </button>
                    {selectedDueItem && (
                      <button className="btn primary ghost-btn" type="button" disabled={startingKnowledgePointId === selectedDueItem.KnowledgePoint.id} onClick={() => void handleStartReview(selectedDueItem)}>
                        {startingKnowledgePointId === selectedDueItem.KnowledgePoint.id ? "生成复习材料..." : "重试开始复习"}
                      </button>
                    )}
                  </div>
                )}
              </article>
            )}

          </div>
        </section>
      </div>
    </div>
  );
}

type ReviewExerciseWorkbenchProps = {
  review: ReviewSessionResponse;
  result: ReviewExerciseResultResponse | null;
  editorCode: string;
  filledBlanks: Record<string, string>;
  explanation: string;
  patchAnswer: ReviewAiPatchAnswer;
  submitDisabled: boolean;
  submitState: "idle" | "submitting" | "done" | "error";
  onCodeChange: (value: string) => void;
  onBlankChange: (blankKey: string, value: string) => void;
  onExplanationChange: (value: string) => void;
  onPatchAnswerChange: Dispatch<SetStateAction<ReviewAiPatchAnswer>>;
  onSubmit: () => void;
};

function ReviewExerciseWorkbench({
  review,
  result,
  editorCode,
  filledBlanks,
  explanation,
  patchAnswer,
  submitDisabled,
  submitState,
  onCodeChange,
  onBlankChange,
  onExplanationChange,
  onPatchAnswerChange,
  onSubmit,
}: ReviewExerciseWorkbenchProps) {
  const exercise = review.review_exercise;
  const isPatchReview = exercise.exercise_type === "review_ai_patch";
  const stateClassName = reviewWorkbenchStateClassName(submitState);

  return (
    <section className="exercise-workbench review-exercise-workbench" aria-label="复习变体练习">
      <div className="wb-header">
        <div className="wb-header-left">
          <span className="wb-kicker">复习练习</span>
          <h2 className="wb-title">{exercise.title}</h2>
        </div>
        <div className="wb-header-right">
          <span className="wb-meta-pill">{exercise.exercise_type}</span>
          <span className="wb-meta-pill">{runtimeLabel(exercise.runtime_profile.runtime_tier)}</span>
          <span className={stateClassName}>{reviewSubmitStateLabel(submitState)}</span>
        </div>
      </div>

      <div className="wb-context-bar">
        <span>{review.knowledge_point.title}</span>
        <span className="wb-context-sep" />
        <span>{reviewStageLabel(review.review_stage)}</span>
        <span className="wb-context-sep" />
        <span>已复习 {review.ReviewState.review_count} 次</span>
      </div>

      <div className="wb-split">
        <div className="wb-editor-pane">
          <div className="wb-prompt">
            <strong>{review.variant_reason}</strong>
            <p>{exercise.prompt_markdown}</p>
          </div>

          {!isPatchReview && exercise.code_blanks.length > 0 && (
            <div className="wb-blanks">
              {exercise.code_blanks.map((blank) => (
                <label className="wb-blank" key={blank.id}>
                  <span className="wb-blank-key">{blank.blank_key}</span>
                  <input
                    className="wb-blank-input"
                    value={filledBlanks[blank.blank_key] ?? ""}
                    placeholder={blank.placeholder}
                    disabled={submitState === "submitting" || submitState === "done"}
                    onChange={(event) => onBlankChange(blank.blank_key, event.target.value)}
                  />
                </label>
              ))}
            </div>
          )}

          {isPatchReview ? (
            <ReviewAiPatchEvidence exercise={exercise} />
          ) : (
            <div className="wb-editor-frame">
              <div className="wb-editor-toolbar">
                <div className="wb-editor-toolbar-left">
                  <span className="wb-editor-lang">{exercise.runtime_profile.language}</span>
                </div>
                <div className="wb-editor-toolbar-right">
                  <button className="wb-toolbar-btn wb-toolbar-btn-primary" type="button" disabled={submitDisabled} onClick={onSubmit}>
                    {reviewSubmitButtonLabel(submitState)}
                  </button>
                </div>
              </div>
              {submitDisabled && submitState !== "done" && <div className="wb-notice">{reviewSubmitNotice(exercise, submitState)}</div>}
              <CodeEditor
                language={exercise.runtime_profile.language}
                value={editorCode}
                onChange={onCodeChange}
                readOnly={submitState === "submitting" || submitState === "done"}
                height="360px"
                dark
              />
            </div>
          )}

          <div className="wb-assist">
            <div className="wb-assist-tabs">
              <button className="wb-assist-tab active" type="button">
                {isPatchReview ? "审查结论" : "解释"}
              </button>
            </div>
            <div className="wb-assist-body">
              {isPatchReview ? (
                <ReviewAiPatchFields
                  answer={patchAnswer}
                  setAnswer={onPatchAnswerChange}
                  submitDisabled={submitDisabled}
                  submitState={submitState}
                  onSubmit={onSubmit}
                />
              ) : (
                <div className="wb-assist-panel">
                  <textarea
                    className="wb-explanation-input"
                    value={explanation}
                    placeholder="用自己的话说明为什么这样补全，后端会据此生成评分结果。"
                    disabled={submitState === "submitting" || submitState === "done"}
                    onChange={(event) => onExplanationChange(event.target.value)}
                  />
                  <div className="wb-assist-controls">
                    <span className="wb-round-badge">提交后才会更新复习节奏</span>
                    <button className="wb-toolbar-btn wb-toolbar-btn-primary" type="button" disabled={submitDisabled} onClick={onSubmit}>
                      {reviewSubmitButtonLabel(submitState)}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        <ReviewResultOutput result={result} submitState={submitState} />
      </div>
    </section>
  );
}

function ReviewAiPatchEvidence({ exercise }: { exercise: ReviewSessionResponse["review_exercise"] }) {
  const metadata = exercise.metadata_json;
  const requirement = stringMeta(metadata, "requirement", exercise.prompt_markdown);
  const originalCode = stringMeta(metadata, "original_code", exercise.starter_code);
  const aiDiff = stringMeta(metadata, "ai_diff", "");
  const reviewFocus = stringMeta(metadata, "review_focus", "判断 AI 改动是否满足当前知识点要求。");

  return (
    <div className="patch-evidence review-patch-evidence">
      <h3>需求</h3>
      <p>{requirement}</p>
      <h3>原始代码</h3>
      <pre>{originalCode}</pre>
      <h3>AI 改动</h3>
      <pre>{aiDiff}</pre>
      <h3>审查焦点</h3>
      <p>{reviewFocus}</p>
    </div>
  );
}

function ReviewAiPatchFields({
  answer,
  setAnswer,
  submitDisabled,
  submitState,
  onSubmit,
}: {
  answer: ReviewAiPatchAnswer;
  setAnswer: Dispatch<SetStateAction<ReviewAiPatchAnswer>>;
  submitDisabled: boolean;
  submitState: "idle" | "submitting" | "done" | "error";
  onSubmit: () => void;
}) {
  return (
    <div className="wb-assist-panel">
      <label className="review-field">
        <span>结论</span>
        <select
          className="wb-select"
          value={answer.verdict}
          disabled={submitState === "submitting" || submitState === "done"}
          onChange={(event) =>
            setAnswer((current) => ({
              ...current,
              verdict: event.target.value as ReviewAiPatchAnswer["verdict"],
            }))
          }
        >
          <option value="fail">不通过</option>
          <option value="pass">通过</option>
          <option value="uncertain">不确定</option>
        </select>
      </label>
      <label className="review-field">
        <span>证据</span>
        <textarea
          className="wb-explanation-input"
          value={answer.evidence}
          placeholder="引用需求、diff 或测试信号。不能只写 tests passed。"
          disabled={submitState === "submitting" || submitState === "done"}
          onChange={(event) => setAnswer((current) => ({ ...current, evidence: event.target.value }))}
        />
      </label>
      <label className="review-field">
        <span>当前知识点风险</span>
        <textarea
          className="wb-explanation-input"
          value={answer.knowledge_point_risk}
          placeholder="说明这个改动会怎样影响当前知识点。"
          disabled={submitState === "submitting" || submitState === "done"}
          onChange={(event) => setAnswer((current) => ({ ...current, knowledge_point_risk: event.target.value }))}
        />
      </label>
      <div className="wb-assist-controls">
        <label className="review-field compact">
          <span>下一步</span>
          <select
            className="wb-select"
            value={answer.next_action}
            disabled={submitState === "submitting" || submitState === "done"}
            onChange={(event) =>
              setAnswer((current) => ({
                ...current,
                next_action: event.target.value as ReviewAiPatchAnswer["next_action"],
              }))
            }
          >
            <option value="request_change">要求修改</option>
            <option value="reject">拒绝改动</option>
            <option value="run_more_tests">补跑测试</option>
            <option value="accept">接受改动</option>
          </select>
        </label>
        <button className="wb-toolbar-btn wb-toolbar-btn-primary" type="button" disabled={submitDisabled} onClick={onSubmit}>
          {reviewSubmitButtonLabel(submitState)}
        </button>
      </div>
      {submitDisabled && submitState !== "done" && <div className="wb-notice">证据和风险说明都填写后才能提交审查结论。</div>}
    </div>
  );
}

function ReviewResultOutput({
  result,
  submitState,
}: {
  result: ReviewExerciseResultResponse | null;
  submitState: "idle" | "submitting" | "done" | "error";
}) {
  const statusLabel = result ? completionResultLabel(result.result) : submitState === "error" ? "提交失败" : "待提交";
  const statusClassName = result ? (result.result !== "failed" ? "success" : "error") : "";

  return (
    <div className="wb-output-pane">
      <div className="wb-output-header">
        <span className="wb-output-title">复习反馈</span>
        <span className={["wb-output-status", statusClassName].filter(Boolean).join(" ")}>{statusLabel}</span>
      </div>
      <div className="wb-output-body">
        {submitState === "submitting" && (
          <div className="wb-output-loading">
            <div className="wb-spinner" />
            正在提交复习结果……
          </div>
        )}
        {submitState === "error" && (
          <div className="wb-output-error">
            <span>提交失败，请检查输入后重试。</span>
          </div>
        )}
        {!result && submitState !== "submitting" && submitState !== "error" && (
          <div className="wb-output-empty">
            <div className="wb-output-empty-icon">↵</div>
            <p>完成左侧练习并提交后，这里会显示后端返回的评分与下次复习安排。</p>
          </div>
        )}
        {result && (
          <div className="review-result-stack">
            <p>{result.feedback}</p>
            <div className="review-result-metrics">
              <div className="review-result-metric">
                <span>结果</span>
                <strong>{completionResultLabel(result.result)}</strong>
              </div>
              <div className="review-result-metric">
                <span>分数</span>
                <strong>{formatScore(result.score)}</strong>
              </div>
              <div className="review-result-metric">
                <span>掌握程度</span>
                <strong>{fsrsRatingLabel(result.fsrs_rating)}</strong>
              </div>
              <div className="review-result-metric">
                <span>下次复习</span>
                <strong>{formatDateTime(result.due_at)}</strong>
              </div>
              <div className="review-result-metric">
                <span>遗忘风险</span>
                <strong>{riskLabel(result.forget_risk)}</strong>
              </div>
            </div>
            {result.weak_points.length > 0 && (
              <div className="review-result-weak-points">
                <span>需要回看</span>
                {result.weak_points.map((point) => (
                  <em key={point}>{point}</em>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function defaultFilledBlanks(review: ReviewSessionResponse): Record<string, string> {
  return Object.fromEntries(review.review_exercise.code_blanks.map((blank) => [blank.blank_key, blank.placeholder]));
}

function defaultReviewPatchAnswer(): ReviewAiPatchAnswer {
  return {
    verdict: "fail",
    evidence: "",
    knowledge_point_risk: "",
    next_action: "request_change",
  };
}

async function restoreReviewConversationMessages(input: {
  userId: string;
  sessionId: string;
  fallbackReview: ReviewSessionResponse;
}): Promise<ConversationMessage[]> {
  try {
    const history = await fetchReviewMessages({
      userId: input.userId,
      sessionId: input.sessionId,
    });
    const restored = history.messages.map(reviewHistoryMessageToConversationMessage);
    if (restored.length > 0) {
      return restored;
    }
  } catch {
    // Fallback keeps the review usable if a legacy backend lacks the history endpoint.
  }
  return initialReviewConversationMessages(input.fallbackReview);
}

function reviewHistoryMessageToConversationMessage(message: ReviewHistoryMessage): ConversationMessage {
  return {
    id: `history-${message.id}`,
    speaker: message.role === "user" ? "user" : "agent",
    text: message.content,
    label: message.role === "agent" ? "Agent" : undefined,
    status: "done",
  };
}

function initialReviewConversationMessages(review: ReviewSessionResponse): ConversationMessage[] {
  const messages = [createMessage("agent", review.initial_agent_message, "Agent")];
  if (isReviewWarmupPending(review.review_stage)) {
    messages.push(createMessage("agent", buildWarmupQuestionMessage(review), "Agent"));
  }
  return messages;
}

function patchOriginalCode(metadata: Record<string, unknown>): string {
  return stringMeta(metadata, "original_code", "");
}

function stringMeta(metadata: Record<string, unknown>, key: string, fallback: string): string {
  const value = metadata[key];
  return typeof value === "string" && value.trim() ? value : fallback;
}

function isReviewWarmupPending(stage: ReviewSessionResponse["review_stage"]): boolean {
  return stage === "warmup" || stage === "warmup_repair";
}

function isWarmupSkipIntent(content: string): boolean {
  return /^(跳过|skip|完全忘了)$/i.test(content.trim());
}

function buildWarmupQuestionMessage(review: ReviewSessionResponse): string {
  const lead = review.review_stage === "warmup_repair" ? "先做一次短修正：" : "先做一个短热身：";
  return `${lead}\n${review.warmup.question}\n\n直接在下面输入框回答；如果想跳过，可以输入“跳过”或点「完全忘了」。`;
}

function buildWarmupResultMessage(result: ReviewWarmupResultResponse): string {
  const lines = [result.warmup.feedback ?? `热身结果：${warmupResultLabel(result.warmup.result)}。`];
  if (isReviewWarmupPending(result.review_stage)) {
    lines.push(`再修正一下：${result.warmup.question}`);
  } else {
    lines.push("热身完成。下面进入同一个知识点的复习变体练习。");
  }
  return lines.join("\n\n");
}

function reviewStageLabel(stage: ReviewSessionResponse["review_stage"]): string {
  if (stage === "warmup") {
    return "热身";
  }
  if (stage === "warmup_repair") {
    return "短修正";
  }
  if (stage === "submitted") {
    return "已完成";
  }
  return "变体练习";
}

function warmupResultLabel(result: ReviewSessionResponse["warmup"]["result"]): string {
  if (result === "correct") {
    return "已唤醒";
  }
  if (result === "skipped") {
    return "已跳过";
  }
  if (result === "unclear") {
    return "不明确";
  }
  if (result === "incorrect") {
    return "需修正";
  }
  return "待完成";
}

function buildSubmittedCode(code: string, filledBlanks: Record<string, string>): string {
  return Object.entries(filledBlanks).reduce((current, [blankKey, value]) => {
    const token = `__${blankKey.toUpperCase()}__`;
    return current.replaceAll(token, value);
  }, code);
}

function formatDateTime(value: string | null): string {
  if (!value) {
    return "未安排";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function riskLabel(value: ReviewDueItem["forget_risk"]): string {
  if (value === "low") {
    return "低";
  }
  if (value === "high") {
    return "高";
  }
  return "正常";
}

function reviewWorkbenchStateClassName(submitState: "idle" | "submitting" | "done" | "error"): string {
  if (submitState === "submitting") {
    return "wb-state wb-state-running";
  }
  if (submitState === "done") {
    return "wb-state wb-state-submitted";
  }
  if (submitState === "error") {
    return "wb-state wb-state-dirty";
  }
  return "wb-state";
}

function reviewSubmitStateLabel(submitState: "idle" | "submitting" | "done" | "error"): string {
  if (submitState === "submitting") {
    return "提交中";
  }
  if (submitState === "done") {
    return "已提交";
  }
  if (submitState === "error") {
    return "提交失败";
  }
  return "待提交";
}

function reviewSubmitButtonLabel(submitState: "idle" | "submitting" | "done" | "error"): string {
  if (submitState === "submitting") {
    return "提交中...";
  }
  if (submitState === "done") {
    return "已提交";
  }
  return "提交复习结果";
}

function reviewSubmitNotice(
  exercise: ReviewSessionResponse["review_exercise"],
  submitState: "idle" | "submitting" | "done" | "error",
): string {
  if (submitState === "submitting") {
    return "当前提交正在处理中，请等待后端返回结果。";
  }
  if (exercise.exercise_type === "review_ai_patch") {
    return "证据和风险说明都填写后才能提交审查结论。";
  }
  return "提交后会由后端更新掌握程度、下次复习和遗忘风险。";
}

function formatScore(score: number): string {
  return Number.isInteger(score) ? String(score) : score.toFixed(2);
}

function createClientId(prefix: string): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  return uuid ? `${prefix}_${uuid}` : `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}
