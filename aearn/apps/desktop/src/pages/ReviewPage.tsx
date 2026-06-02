import { startTransition, useEffect, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import { buildReviewMessageSSEUrl, fetchTodayReviews, startReviewSession, submitReviewExerciseResult, submitReviewWarmupResult } from "../api";
import type { ConversationMessage, NoteContext } from "../appTypes";
import { AssistantUIThread } from "../components/AssistantUIThread";
import { useSSE } from "../hooks/useSSE";
import { formatErrorMessage } from "../lib/errorMessages";
import { createMessage } from "../lib/learningHelpers";
import { useAppStore } from "../stores/useAppStore";
import type {
  ReviewDueItem,
  ReviewAiPatchAnswer,
  ReviewExerciseResultResponse,
  ReviewSessionResponse,
  UserProfile,
} from "../types";

type ReviewPageProps = {
  isActive: boolean;
  user: UserProfile | null;
  messages: ConversationMessage[];
  onActiveNoteContextChange: (context: NoteContext | null) => void;
};

type ReviewStreamRequest = {
  endpoint: string;
  requestId: string;
  assistantMessageId: string;
  body: {
    role: "user";
    content: string;
    client_message_id: string;
  };
};

const REVIEW_QUICK_REPLIES = ["我记得", "不太确定", "完全忘了"];

export function ReviewPage({ isActive, user, messages, onActiveNoteContextChange }: ReviewPageProps) {
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
    if (content.length === 0 || isStreaming || !activeReview) return;

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
      startTransition(() => {
        setActiveReview(response);
        setEditorCode(response.review_exercise.starter_code);
        setFilledBlanks(defaultFilledBlanks(response));
        setExplanation("");
        setWarmupAnswer(response.warmup.last_answer ?? "");
        setReviewPatchAnswer(defaultReviewPatchAnswer());
      });
      // Add AI greeting as first message in thread
      store.addReviewMessage(
        createMessage("agent", response.initial_agent_message, "Agent"),
      );
    } catch (error) {
      setErrorMessage(formatErrorMessage(error, "无法开始复习"));
    } finally {
      setStartingKnowledgePointId(null);
    }
  }

  async function handleWarmupSubmit(action: "answer" | "skip") {
    if (!activeReview || warmupState === "submitting") {
      return;
    }
    setWarmupState("submitting");
    setErrorMessage(null);
    try {
      const response = await submitReviewWarmupResult({
        sessionId: activeReview.session_id,
        action,
        answer: action === "skip" ? undefined : warmupAnswer,
      });
      startTransition(() => {
        setActiveReview((current) =>
          current
            ? {
                ...current,
                review_stage: response.review_stage,
                review_stage_state: response.review_stage_state,
                warmup: response.warmup,
              }
            : current,
        );
        setWarmupAnswer(response.warmup.last_answer ?? warmupAnswer);
        setWarmupState("idle");
      });
    } catch (error) {
      setWarmupState("error");
      setErrorMessage(formatErrorMessage(error, "热身提交失败"));
    }
  }

  async function handleSubmitReview() {
    if (!activeReview || submitState === "submitting") {
      return;
    }
    setSubmitState("submitting");
    setErrorMessage(null);
    try {
      const exercise = activeReview.review_exercise;
      const result = await submitReviewExerciseResult({
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
  const warmupAnswerBlank = warmupAnswer.trim().length === 0;
  const patchAnswerComplete =
    activeExercise?.exercise_type !== "review_ai_patch" ||
    (reviewPatchAnswer.evidence.trim().length > 0 && reviewPatchAnswer.knowledge_point_risk.trim().length > 0);
  const submitDisabled = !activeReview || warmupPending || !patchAnswerComplete || submitState === "submitting" || submitState === "done";
  const composerSessionActive = Boolean(activeReview);

  return (
    <div className="review-screen">
      <div className="review-thread-wrap">
        <section className="conversation" aria-label="复习对话" ref={conversationScrollRef}>
          <div className="thread">
            {!activeReview && (
              <div className="lesson-title">
                <p>独立复习会话，针对薄弱知识点进行变体练习。</p>
              </div>
            )}

            <AssistantUIThread
              messages={messages}
              isStreaming={isStreaming}
              sessionActive={composerSessionActive}
              onSend={handleComposerSubmit}
              hideNoteButton
              quickReplies={composerSessionActive && messages.length <= 1 ? REVIEW_QUICK_REPLIES : undefined}
              placeholder={
                isStreaming
                  ? "AI 正在回复……"
                  : !composerSessionActive
                    ? "先开始一个复习会话……"
                    : "用自己的话复述，或请求提示……"
              }
              ariaLabel="复习输入框"
              guidanceText={!composerSessionActive ? "点击上方「开始复习」后，可以在这里和 AI 对话。" : undefined}
            />

            <section className="exercise-workbench" aria-label="今日复习闭环">
              <div className="exercise-head">
                <div>
                  <span className="eyebrow">Review Queue</span>
                  <h2>今日待复习</h2>
                </div>
                <button className="btn ghost" type="button" disabled={!user || loadState === "loading"} onClick={() => void loadDueReviews()}>
                  {loadState === "loading" ? "刷新中..." : "刷新"}
                </button>
              </div>

              {!user && <div className="tool-card">先完成建档和学习计划后，复习页才会加载待复习内容。</div>}
              {errorMessage && <div className="tool-card">错误：{errorMessage}</div>}
              {user && loadState === "ready" && dueItems.length === 0 && <div className="tool-card">当前没有已到期复习项。</div>}

              {dueItems.length > 0 && (
                <div className="review-recap-grid" aria-label="待复习知识点">
                  {dueItems.map((item) => (
                    <article className="review-card active" key={item.KnowledgePoint.id}>
                      <h3>{item.KnowledgePoint.title}</h3>
                      <p>
                        下次复习：{formatDateTime(item.ReviewState.due_at)} · 遗忘风险：{riskLabel(item.forget_risk)}
                      </p>
                      <p>
                        已复习 {item.ReviewState.review_count} 次
                      </p>
                      <button
                        className="btn primary"
                        type="button"
                        disabled={startingKnowledgePointId === item.KnowledgePoint.id}
                        onClick={() => void handleStartReview(item)}
                      >
                        {startingKnowledgePointId === item.KnowledgePoint.id ? "生成复习材料..." : "开始复习"}
                      </button>
                    </article>
                  ))}
                </div>
              )}

              {activeReview && (
                <article className="review-card active review-warmup-card" aria-label="复习热身">
                  <div className="exercise-head">
                    <div>
                      <span className="eyebrow">Warmup</span>
                      <h2>先短回忆，再做变体</h2>
                    </div>
                    <span className="runtime-pill">{reviewStageLabel(activeReview.review_stage)}</span>
                  </div>
                  <p>{activeReview.warmup.question}</p>
                  {activeReview.warmup.feedback && <div className="tool-card">{activeReview.warmup.feedback}</div>}
                  {warmupPending ? (
                    <div className="warmup-actions">
                      <textarea
                        value={warmupAnswer}
                        placeholder="用一句话说出这个知识点最容易出错的地方。"
                        onChange={(event) => setWarmupAnswer(event.target.value)}
                      />
                      <div className="button-row">
                        <button className="btn primary" type="button" disabled={warmupState === "submitting" || warmupAnswerBlank} onClick={() => void handleWarmupSubmit("answer")}>
                          {warmupState === "submitting" ? "记录中..." : "提交热身"}
                        </button>
                        <button className="btn ghost" type="button" disabled={warmupState === "submitting"} onClick={() => void handleWarmupSubmit("skip")}>
                          跳过热身
                        </button>
                      </div>
                    </div>
                  ) : (
                    <p>热身结果：{warmupResultLabel(activeReview.warmup.result)}。掌握程度和复习安排会在你提交下面的变体练习后更新。</p>
                  )}
                </article>
              )}

              {activeReview && activeExercise && (
                <article className="review-card active" aria-label="复习变体练习">
                  <div className="exercise-head">
                    <div>
                      <span className="eyebrow">变体练习</span>
                      <h2>{activeExercise.title}</h2>
                    </div>
                    <span className="runtime-pill">{runtimeTierLabel(activeExercise.runtime_profile.runtime_tier)}</span>
                  </div>
                  <p>{activeReview.variant_reason}</p>

                  {activeExercise.exercise_type === "review_ai_patch" ? (
                    <ReviewAiPatchForm
                      exercise={activeExercise}
                      answer={reviewPatchAnswer}
                      setAnswer={setReviewPatchAnswer}
                      submitDisabled={submitDisabled}
                      submitState={submitState}
                      onSubmit={() => void handleSubmitReview()}
                    />
                  ) : (
                    <div className="exercise-grid">
                      <div className="exercise-panel">
                        <p>{activeExercise.prompt_markdown}</p>
                        <div className="blank-grid">
                          {activeExercise.code_blanks.map((blank) => (
                            <label key={blank.id}>
                              {blank.blank_key}
                              <input
                                value={filledBlanks[blank.blank_key] ?? ""}
                                onChange={(event) =>
                                  setFilledBlanks((current) => ({
                                    ...current,
                                    [blank.blank_key]: event.target.value,
                                  }))
                                }
                              />
                            </label>
                          ))}
                        </div>
                        <label className="exercise-editor">
                          解释
                          <textarea
                            value={explanation}
                            placeholder="用自己的话说明为什么这样补全，后端会据此生成评分结果。"
                            onChange={(event) => setExplanation(event.target.value)}
                          />
                        </label>
                      </div>

                      <div className="exercise-editor">
                        <label>
                          代码
                          <textarea value={editorCode} onChange={(event) => setEditorCode(event.target.value)} />
                        </label>
                        <button className="btn primary" type="button" disabled={submitDisabled} onClick={() => void handleSubmitReview()}>
                          {submitState === "submitting" ? "提交中..." : submitState === "done" ? "已提交" : warmupPending ? "先完成热身" : "提交复习结果"}
                        </button>
                      </div>
                    </div>
                  )}
                </article>
              )}

              {reviewResult && (
                <article className="submit-summary">
                  <h3>复习结果</h3>
                  <p>{reviewResult.feedback}</p>
                  <div className="review-recap-grid">
                    <div className="review-card">
                      <h3>{fsrsRatingLabel(reviewResult.fsrs_rating)}</h3>
                      <p>掌握程度</p>
                    </div>
                    <div className="review-card">
                      <h3>{formatDateTime(reviewResult.due_at)}</h3>
                      <p>下次复习</p>
                    </div>
                    <div className="review-card">
                      <h3>{riskLabel(reviewResult.forget_risk)}</h3>
                      <p>遗忘风险</p>
                    </div>
                  </div>
                </article>
              )}
            </section>

          </div>
        </section>
      </div>
    </div>
  );
}

function ReviewAiPatchForm({
  exercise,
  answer,
  setAnswer,
  submitDisabled,
  submitState,
  onSubmit,
}: {
  exercise: ReviewSessionResponse["review_exercise"];
  answer: ReviewAiPatchAnswer;
  setAnswer: Dispatch<SetStateAction<ReviewAiPatchAnswer>>;
  submitDisabled: boolean;
  submitState: "idle" | "submitting" | "done" | "error";
  onSubmit: () => void;
}) {
  const metadata = exercise.metadata_json;
  const requirement = stringMeta(metadata, "requirement", exercise.prompt_markdown);
  const originalCode = stringMeta(metadata, "original_code", exercise.starter_code);
  const aiDiff = stringMeta(metadata, "ai_diff", "");
  const reviewFocus = stringMeta(metadata, "review_focus", "判断 AI 改动是否满足当前知识点要求。");

  return (
    <div className="review-patch-grid">
      <div className="exercise-panel">
        <p>{exercise.prompt_markdown}</p>
        <div className="patch-evidence">
          <h3>需求</h3>
          <p>{requirement}</p>
          <h3>原始代码</h3>
          <pre>{originalCode}</pre>
          <h3>AI 改动</h3>
          <pre>{aiDiff}</pre>
          <h3>审查焦点</h3>
          <p>{reviewFocus}</p>
        </div>
      </div>
      <div className="exercise-panel">
        <label>
          结论
          <select
            value={answer.verdict}
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
        <label className="exercise-editor">
          证据
          <textarea
            value={answer.evidence}
            placeholder="引用需求、diff 或测试信号。不能只写 tests passed。"
            onChange={(event) => setAnswer((current) => ({ ...current, evidence: event.target.value }))}
          />
        </label>
        <label className="exercise-editor">
          当前知识点风险
          <textarea
            value={answer.knowledge_point_risk}
            placeholder="说明这个改动会怎样影响当前知识点。"
            onChange={(event) => setAnswer((current) => ({ ...current, knowledge_point_risk: event.target.value }))}
          />
        </label>
        <label>
          下一步
          <select
            value={answer.next_action}
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
        <button className="btn primary" type="button" disabled={submitDisabled} onClick={onSubmit}>
          {submitState === "submitting" ? "提交中..." : submitState === "done" ? "已提交" : "提交审查结论"}
        </button>
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

function patchOriginalCode(metadata: Record<string, unknown>): string {
  return stringMeta(metadata, "original_code", "");
}

function stringMeta(metadata: Record<string, unknown>, key: string, fallback: string): string {
  const value = metadata[key];
  return typeof value === "string" && value.trim() ? value : fallback;
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

function runtimeTierLabel(tier: string): string {
  if (tier === "browser_preview") {
    return "浏览器预览";
  }
  if (tier === "python_stdout_test") {
    return "Python 测试";
  }
  return "静态补全";
}

function fsrsRatingLabel(rating: string | number): string {
  if (rating === "again" || rating === "Again" || rating === 1) {
    return "需要重学";
  }
  if (rating === "hard" || rating === "Hard" || rating === 2) {
    return "较困难";
  }
  if (rating === "good" || rating === "Good" || rating === 3) {
    return "良好";
  }
  if (rating === "easy" || rating === "Easy" || rating === 4) {
    return "轻松掌握";
  }
  return String(rating);
}

function createClientId(prefix: string): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  return uuid ? `${prefix}_${uuid}` : `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}
