import { startTransition, useEffect, useState } from "react";

import { fetchTodayReviews, startReviewSession, submitReviewExerciseResult } from "../api";
import type { ConversationMessage } from "../appTypes";
import type {
  ReviewDueItem,
  ReviewExerciseResultResponse,
  ReviewSessionResponse,
  RunExerciseResponse,
  SubmitExerciseResponse,
  UserProfile,
} from "../types";
import { ApiRequestError } from "../types";
import { ReviewRecap } from "../components/ReviewRecap";
import { ThreadMessages } from "../components/ThreadMessages";

type ReviewPageProps = {
  isActive: boolean;
  user: UserProfile | null;
  messages: ConversationMessage[];
  lastSubmit: SubmitExerciseResponse | null;
  lastRun: RunExerciseResponse | null;
};

export function ReviewPage({ isActive, user, messages, lastSubmit, lastRun }: ReviewPageProps) {
  const [dueItems, setDueItems] = useState<ReviewDueItem[]>([]);
  const [loadState, setLoadState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [activeReview, setActiveReview] = useState<ReviewSessionResponse | null>(null);
  const [editorCode, setEditorCode] = useState("");
  const [filledBlanks, setFilledBlanks] = useState<Record<string, string>>({});
  const [explanation, setExplanation] = useState("");
  const [submitState, setSubmitState] = useState<"idle" | "submitting" | "done" | "error">("idle");
  const [reviewResult, setReviewResult] = useState<ReviewExerciseResultResponse | null>(null);

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
      setErrorMessage(formatError(error, "无法加载今日复习"));
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
    } catch (error) {
      setErrorMessage(formatError(error, "无法开始复习"));
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
      await loadDueReviews();
    } catch (error) {
      setSubmitState("error");
      setErrorMessage(formatError(error, "复习提交失败"));
    }
  }

  useEffect(() => {
    if (!isActive) {
      return;
    }
    const controller = new AbortController();
    void loadDueReviews(controller.signal);
    return () => controller.abort();
  }, [isActive, user?.id]);

  const activeExercise = activeReview?.review_exercise ?? null;
  const submittedCode = activeExercise ? buildSubmittedCode(editorCode, filledBlanks) : editorCode;
  const submitDisabled = !activeReview || submitState === "submitting" || submitState === "done";

  return (
    <div className="review-screen">
      <div className="review-thread-wrap">
        <section className="conversation" aria-label="复习新会话">
          <div className="thread">
            <div className="lesson-title">
              <p>这是一个独立复习会话。待复习列表、变体练习、下一次 due_at 和 forget_risk 都来自后端。</p>
            </div>

            <ThreadMessages messages={messages} />

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

              {!user && <div className="tool-card">先完成建档和学习计划后，复习页才会读取后端 due queue。</div>}
              {errorMessage && <div className="tool-card">错误：{errorMessage}</div>}
              {user && loadState === "ready" && dueItems.length === 0 && <div className="tool-card">当前没有已到期复习项。</div>}

              {dueItems.length > 0 && (
                <div className="review-recap-grid" aria-label="待复习知识点">
                  {dueItems.map((item) => (
                    <article className="review-card active" key={item.KnowledgePoint.id}>
                      <h3>{item.KnowledgePoint.title}</h3>
                      <p>
                        due_at：{formatDateTime(item.ReviewState.due_at)} · 风险：{riskLabel(item.forget_risk)}
                      </p>
                      <p>
                        复习次数：{item.ReviewState.review_count} · 上次评分：{item.ReviewState.last_fsrs_rating ?? "未评分"}
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
                      <span className="eyebrow">Variant</span>
                      <h2>{activeExercise.title}</h2>
                    </div>
                    <span>{activeExercise.runtime_profile.runtime_tier}</span>
                  </div>
                  <p>{activeReview.variant_reason}</p>
                  <div className="tool-card">{activeReview.initial_agent_message}</div>

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
                      <pre className="tool-card">{submittedCode}</pre>
                      <button className="btn primary" type="button" disabled={submitDisabled} onClick={() => void handleSubmitReview()}>
                        {submitState === "submitting" ? "提交中..." : submitState === "done" ? "已提交" : "提交复习结果"}
                      </button>
                    </div>
                  </div>
                </article>
              )}

              {reviewResult && (
                <article className="submit-summary">
                  <h3>后端复习结果</h3>
                  <p>{reviewResult.feedback}</p>
                  <div className="review-recap-grid">
                    <div className="review-card">
                      <h3>{reviewResult.fsrs_rating}</h3>
                      <p>FSRS rating</p>
                    </div>
                    <div className="review-card">
                      <h3>{formatDateTime(reviewResult.due_at)}</h3>
                      <p>下一次 due_at</p>
                    </div>
                    <div className="review-card">
                      <h3>{riskLabel(reviewResult.forget_risk)}</h3>
                      <p>forget_risk</p>
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
                  <p>最近一次提交已经写回复习状态。下一轮会优先追打 {lastSubmit.code_completion_result.weak_points[0] ?? "状态变量生命周期"}。</p>
                  <div className="tool-card">
                    FSRS：{lastSubmit.code_completion_result.fsrs_rating} · 下一步：{lastSubmit.next_action}
                  </div>
                </div>
              </article>
            )}

            <ReviewRecap lastSubmit={lastSubmit} lastRun={lastRun} />
          </div>
        </section>
      </div>
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

function formatError(error: unknown, fallback: string): string {
  if (error instanceof ApiRequestError) {
    return `${error.apiError.code}: ${error.apiError.message}`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return fallback;
}
