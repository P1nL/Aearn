import { startTransition, useEffect, useRef, useState } from "react";

import { buildReviewMessageSSEUrl, fetchTodayReviews, startReviewSession, submitReviewExerciseResult } from "../api";
import type { ConversationMessage, NoteContext } from "../appTypes";
import { AssistantThread } from "../components/AssistantThread";
import { LearningComposer } from "../components/LearningComposer";
import { ReviewRecap } from "../components/ReviewRecap";
import { useSSE } from "../hooks/useSSE";
import { formatErrorMessage } from "../lib/errorMessages";
import { createMessage } from "../lib/learningHelpers";
import { useAppStore } from "../stores/useAppStore";
import type {
  ReviewDueItem,
  ReviewExerciseResultResponse,
  ReviewSessionResponse,
  RunExerciseResponse,
  SubmitExerciseResponse,
  UserProfile,
} from "../types";

type ReviewPageProps = {
  isActive: boolean;
  user: UserProfile | null;
  messages: ConversationMessage[];
  lastSubmit: SubmitExerciseResponse | null;
  lastRun: RunExerciseResponse | null;
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

export function ReviewPage({ isActive, user, messages, lastSubmit, lastRun, onActiveNoteContextChange }: ReviewPageProps) {
  const store = useAppStore();
  const [dueItems, setDueItems] = useState<ReviewDueItem[]>([]);
  const [loadState, setLoadState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [activeReview, setActiveReview] = useState<ReviewSessionResponse | null>(null);
  const [editorCode, setEditorCode] = useState("");
  const [filledBlanks, setFilledBlanks] = useState<Record<string, string>>({});
  const [explanation, setExplanation] = useState("");
  const [submitState, setSubmitState] = useState<"idle" | "submitting" | "done" | "error">("idle");
  const [reviewResult, setReviewResult] = useState<ReviewExerciseResultResponse | null>(null);
  const [composerInput, setComposerInput] = useState("");
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

  function handleComposerSubmit() {
    const content = composerInput.trim();
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
    setComposerInput("");
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
    setSubmitState("idle");
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
      });
      // Add AI greeting as first message in thread
      store.addReviewMessage(
        createMessage("agent", response.initial_agent_message, "Agent"),
      );
    } catch (error) {
      setErrorMessage(formatErrorMessage(error, "无法开始复习"));
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
        code: buildSubmittedCode(editorCode, filledBlanks),
        filledBlanks,
        explanation,
      });
      startTransition(() => {
        setReviewResult(result);
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
  const submitDisabled = !activeReview || submitState === "submitting" || submitState === "done";
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

            <AssistantThread messages={messages} />

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
                      <button className="btn primary" type="button" onClick={() => void handleStartReview(item)}>
                        开始复习
                      </button>
                    </article>
                  ))}
                </div>
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
                        {submitState === "submitting" ? "提交中..." : submitState === "done" ? "已提交" : "提交复习结果"}
                      </button>
                    </div>
                  </div>
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

            {lastSubmit && (
              <article className="message agent">
                <div className="avatar">A</div>
                <div className="bubble">
                  <div className="bubble-label">Agent</div>
                  <p>复习已完成。下一轮会重点巩固「{lastSubmit.code_completion_result.weak_points[0] ?? "状态变量生命周期"}」。</p>
                  <div className="tool-card">
                    掌握程度：{fsrsRatingLabel(lastSubmit.code_completion_result.fsrs_rating)} · 建议：{nextActionLabel(lastSubmit.next_action)}
                  </div>
                </div>
              </article>
            )}

            <ReviewRecap lastSubmit={lastSubmit} lastRun={lastRun} />
          </div>
        </section>
      </div>

      <LearningComposer
        value={composerInput}
        onChange={setComposerInput}
        onSubmit={handleComposerSubmit}
        disabled={isStreaming}
        streaming={isStreaming}
        sessionActive={composerSessionActive}
        hideNoteButton
        quickReplies={composerSessionActive && messages.length <= 1 ? REVIEW_QUICK_REPLIES : undefined}
        placeholder={isStreaming ? "AI 正在回复……" : !composerSessionActive ? "先开始一个复习会话……" : "用自己的话复述，或请求提示……"}
        ariaLabel="复习输入框"
        guidanceText={!composerSessionActive ? "点击上方「开始复习」后，可以在这里和 AI 对话。" : undefined}
      />
    </div>
  );
}

function defaultFilledBlanks(review: ReviewSessionResponse): Record<string, string> {
  return Object.fromEntries(review.review_exercise.code_blanks.map((blank) => [blank.blank_key, blank.placeholder]));
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
  if (rating === "again" || rating === 1) {
    return "需要重学";
  }
  if (rating === "hard" || rating === 2) {
    return "较困难";
  }
  if (rating === "good" || rating === 3) {
    return "良好";
  }
  if (rating === "easy" || rating === 4) {
    return "轻松掌握";
  }
  return String(rating);
}

function nextActionLabel(action: string): string {
  if (action === "show_hint") {
    return "获取提示";
  }
  if (action === "explain_error") {
    return "解释错误";
  }
  if (action === "review_variant") {
    return "复习变体";
  }
  if (action === "schedule_review") {
    return "安排复习";
  }
  if (action === "advance_next") {
    return "继续下一步";
  }
  return "重新运行";
}

function createClientId(prefix: string): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  return uuid ? `${prefix}_${uuid}` : `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}
