import { useEffect, useMemo, useState } from "react";

import {
  createReviewAttempt,
  createReviewSession,
  fetchReviewAttempt,
  fetchReviewSession,
  finalizeReviewSession,
  recordReviewWarmup,
  requestReviewHint,
} from "../../api";
import { getErrorInfo } from "../../lib/errorMessages";
import type {
  LearningTrackDetail,
  ModelCodeReviewSubmission,
  ModelReviewFinding,
  ModelReviewVerdict,
  ReviewAttempt,
  ReviewHint,
  ReviewQueue,
  ReviewQueueItem,
  ReviewSession,
  ReviewSessionItem,
  TutorContextReferenceDraft,
} from "../../types";
import { ModelCodeReviewFindingEditor } from "./lesson/ModelCodeReviewFindingEditor";

type ReviewSessionPanelProps = {
  userId: string;
  track: LearningTrackDetail;
  queue: ReviewQueue;
  initialKnowledgeKey?: string | null;
  initialSessionId?: string | null;
  onSessionChange?: (sessionId: string | null) => void;
  onQueueRefresh?: () => Promise<void> | void;
  onContextReference: (draft: TutorContextReferenceDraft, label: string) => void;
};

type BusyAction = "create" | "warmup" | "hint" | "attempt" | "poll" | "finalize" | null;

export function ReviewSessionPanel({
  userId,
  track,
  queue,
  initialKnowledgeKey,
  initialSessionId,
  onSessionChange,
  onQueueRefresh,
  onContextReference,
}: ReviewSessionPanelProps) {
  const preferred = queue.items.find((item) => item.knowledge_key === initialKnowledgeKey)
    ?? queue.critical_prerequisite_gate
    ?? queue.items[0]
    ?? null;
  const [selectedKnowledgeKey, setSelectedKnowledgeKey] = useState<string | null>(preferred?.knowledge_key ?? null);
  const [session, setSession] = useState<ReviewSession | null>(null);
  const [loading, setLoading] = useState(Boolean(initialSessionId));
  const [busy, setBusy] = useState<BusyAction>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [hint, setHint] = useState<ReviewHint | null>(null);
  const [submission, setSubmission] = useState("");
  const [reviewDraft, setReviewDraft] = useState<ModelCodeReviewSubmission>(emptyReviewDraft());
  const [latestAttempt, setLatestAttempt] = useState<ReviewAttempt | null>(null);

  useEffect(() => {
    setSelectedKnowledgeKey(preferred?.knowledge_key ?? null);
  }, [preferred?.knowledge_key]);

  useEffect(() => {
    if (!initialSessionId) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setErrorMessage(null);
    void fetchReviewSession(userId, track.track_id, initialSessionId, controller.signal)
      .then((next) => {
        if (!controller.signal.aborted) {
          setSession(next);
          setSelectedKnowledgeKey(next.knowledge_key);
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setErrorMessage(getErrorInfo(error).message);
          onSessionChange?.(null);
        }
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [initialSessionId, onSessionChange, track.track_id, userId]);

  const currentItem = useMemo(
    () => session?.items.find((item) => item.attempt?.status !== "terminal") ?? session?.items[session.items.length - 1] ?? null,
    [session],
  );

  useEffect(() => {
    setHint(null);
    setSubmission(starterText(currentItem));
    setReviewDraft(emptyReviewDraft());
    setLatestAttempt(null);
  }, [currentItem?.exercise.exercise_version_id]);

  async function refreshSession(): Promise<ReviewSession | null> {
    if (!session) return null;
    const next = await fetchReviewSession(userId, track.track_id, session.session_id);
    setSession(next);
    return next;
  }

  async function startSession(item: ReviewQueueItem) {
    if (busy) return;
    setBusy("create");
    setErrorMessage(null);
    try {
      const next = await createReviewSession({
        userId, trackId: track.track_id, knowledgeKey: item.knowledge_key, expectedTrackVersion: track.version,
        expectedScheduleVersion: item.schedule_version, maxItems: 1,
        clientActionId: createReviewActionId(`review-create-${item.knowledge_key}`),
      });
      setSession(next);
      setSelectedKnowledgeKey(next.knowledge_key);
      onSessionChange?.(next.session_id);
    } catch (error) {
      setErrorMessage(getErrorInfo(error).message);
    } finally {
      setBusy(null);
    }
  }

  async function warmup(responseKind: "answered" | "skipped", confidence?: "low" | "medium" | "high") {
    if (!session || busy) return;
    setBusy("warmup");
    setErrorMessage(null);
    try {
      const next = await recordReviewWarmup({
        userId, trackId: track.track_id, sessionId: session.session_id, responseKind, confidence,
        expectedSessionVersion: session.version, clientActionId: createReviewActionId("review-warmup"),
      });
      setSession(next);
    } catch (error) {
      setErrorMessage(getErrorInfo(error).message);
    } finally {
      setBusy(null);
    }
  }

  async function requestHint() {
    if (!session || !currentItem || busy) return;
    setBusy("hint");
    setErrorMessage(null);
    try {
      const next = await requestReviewHint({
        userId, trackId: track.track_id, sessionId: session.session_id, itemId: currentItem.item_id,
        hintLevel: Math.min(3, (hint?.hint_level ?? 0) + 1), expectedSessionVersion: session.version,
        expectedItemVersion: currentItem.version, clientActionId: createReviewActionId("review-hint"),
      });
      setHint(next);
      await refreshSession();
    } catch (error) {
      setErrorMessage(getErrorInfo(error).message);
    } finally {
      setBusy(null);
    }
  }

  async function submitAttempt() {
    if (!session || !currentItem || busy || currentItem.attempt?.status === "terminal") return;
    const exercise = currentItem.exercise;
    const modelReview = exercise.exercise_type === "model_code_review";
    if (exercise.exercise_type === "model_code_review" && reviewSubmissionErrors(reviewDraft, exercise.starter_artifact.line_count).length > 0) return;
    if (exercise.exercise_type !== "model_code_review" && !submission.trim()) return;
    setBusy("attempt");
    setErrorMessage(null);
    try {
      let attempt = modelReview
        ? await createReviewAttempt({
            userId, trackId: track.track_id, sessionId: session.session_id, itemId: currentItem.item_id,
            reviewSubmission: reviewDraft, expectedSessionVersion: session.version, expectedItemVersion: currentItem.version,
            clientActionId: createReviewActionId("review-attempt"),
          })
        : await createReviewAttempt({
            userId, trackId: track.track_id, sessionId: session.session_id, itemId: currentItem.item_id,
            submission, expectedSessionVersion: session.version, expectedItemVersion: currentItem.version,
            clientActionId: createReviewActionId("review-attempt"),
          });
      setLatestAttempt(attempt);
      if (attempt.status === "pending") {
        attempt = await pollAttempt(attempt.attempt_id);
        setLatestAttempt(attempt);
      }
      await refreshSession();
      if (attempt.status === "pending") setErrorMessage("受控执行仍在队列中，可以继续刷新同一 Attempt。");
    } catch (error) {
      setErrorMessage(getErrorInfo(error).message);
    } finally {
      setBusy(null);
    }
  }

  async function pollAttempt(attemptId: string) {
    if (!session) throw new Error("没有可刷新的 Review Attempt");
    let latest = await fetchReviewAttempt(userId, track.track_id, session.session_id, attemptId);
    for (let index = 0; latest.status === "pending" && index < 18; index += 1) {
      await new Promise((resolve) => globalThis.setTimeout(resolve, 850));
      latest = await fetchReviewAttempt(userId, track.track_id, session.session_id, attemptId);
    }
    return latest;
  }

  async function pollCurrentAttempt() {
    const attemptId = latestAttempt?.attempt_id ?? currentItem?.attempt?.attempt_id;
    if (!session || !attemptId || busy) return;
    setBusy("poll");
    setErrorMessage(null);
    try {
      const latest = await pollAttempt(attemptId);
      setLatestAttempt(latest);
      await refreshSession();
      if (latest.status === "pending") setErrorMessage("受控执行仍未完成，请稍后刷新同一 Attempt。");
    } catch (error) {
      setErrorMessage(getErrorInfo(error).message);
    } finally {
      setBusy(null);
    }
  }

  async function finalize() {
    if (!session || session.state !== "ready_to_finalize" || busy) return;
    setBusy("finalize");
    setErrorMessage(null);
    try {
      const next = await finalizeReviewSession({
        userId, trackId: track.track_id, sessionId: session.session_id, expectedSessionVersion: session.version,
        clientActionId: createReviewActionId("review-finalize"),
      });
      setSession(next);
      await onQueueRefresh?.();
    } catch (error) {
      setErrorMessage(getErrorInfo(error).message);
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <ReviewStatus title="正在恢复复习" body="服务器正在读取 ReviewSession、版本和已有 Attempt。" />;

  if (!session) {
    return (
      <section className="review-session-panel" aria-labelledby="review-session-title">
        <header className="review-session-heading">
          <div><p className="tutor-panel-eyebrow">间隔复习</p><h1 id="review-session-title">今天需要重新巩固什么？</h1><p>到期、风险和掌握状态均由服务端计算。选择一项后会创建可恢复的 ReviewSession。</p></div>
          <span>{queue.due_count} 项到期</span>
        </header>
        {errorMessage ? <p className="lesson-gate-error" role="alert">{errorMessage}</p> : null}
        {queue.items.length === 0 ? <ReviewStatus title="今天没有到期复习" body="可以回到课程继续当前知识点；系统会在权威 schedule 到期后显示入口。" /> : (
          <div className="review-queue-list">
            {queue.items.map((item) => (
              <button className={`review-queue-item ${item.risk_level}${item.knowledge_key === selectedKnowledgeKey ? " selected" : ""}`} key={item.schedule_id} type="button" disabled={busy !== null} onClick={() => { setSelectedKnowledgeKey(item.knowledge_key); void startSession(item); }}>
                <span className="review-risk-dot" aria-hidden="true" />
                <span><strong>{item.title}</strong><small>{item.knowledge_key} · {riskLabel(item.risk_level)}风险</small><em>{item.required_capabilities.join(" · ")}</em></span>
                <b>{busy === "create" && item.knowledge_key === selectedKnowledgeKey ? "正在创建……" : "开始"}</b>
              </button>
            ))}
          </div>
        )}
      </section>
    );
  }

  if (session.state === "blocked") {
    return <ReviewStatus title="本次复习暂时受阻" body="服务器没有找到符合当前执行与版本 contract 的复习候选。" detail={session.failure_code ?? undefined} actionLabel={session.recoverable ? "重新读取" : undefined} onAction={session.recoverable ? () => void refreshSession() : undefined} />;
  }

  if (session.stage === "warmup") {
    return (
      <section className="review-session-panel review-warmup" aria-labelledby="review-warmup-title">
        <header className="review-session-heading"><div><p className="tutor-panel-eyebrow">复习热身</p><h1 id="review-warmup-title">先判断自己的熟悉程度</h1><p>这不是评分。你的回答只帮助服务器记录本次复习的独立性与上下文。</p></div><span>{session.knowledge_key}</span></header>
        <div className="review-warmup-actions" aria-label="热身熟悉程度">
          {(["low", "medium", "high"] as const).map((confidence) => <button type="button" key={confidence} disabled={busy !== null} onClick={() => void warmup("answered", confidence)}><strong>{confidenceLabel(confidence)}</strong><span>{confidenceCopy(confidence)}</span></button>)}
        </div>
        <button className="tutor-text-button review-skip-warmup" type="button" disabled={busy !== null} onClick={() => void warmup("skipped")}>跳过自评，直接开始</button>
        {errorMessage ? <p className="lesson-gate-error" role="alert">{errorMessage}</p> : null}
      </section>
    );
  }

  const referencedAttempt = latestAttempt?.status === "terminal" ? latestAttempt : terminalAttemptFromSession(session);
  return (
    <section className="review-session-panel" aria-labelledby="review-practice-title">
      <header className="review-session-heading">
        <div><p className="tutor-panel-eyebrow">ReviewSession · {session.stage}</p><h1 id="review-practice-title">{currentItem?.exercise.title ?? "复习总结"}</h1><p>{session.knowledge_key} · 服务器版本 {session.version}</p></div>
        <span className={`review-session-state ${session.state}`}>{reviewStateLabel(session.state)}</span>
      </header>

      {currentItem ? <ReviewExerciseForm item={currentItem} submission={submission} reviewDraft={reviewDraft} disabled={busy !== null || currentItem.attempt?.status === "terminal"} onSubmissionChange={setSubmission} onReviewDraftChange={setReviewDraft} /> : null}
      {hint ? <aside className="lesson-gate-hint review-hint" aria-live="polite"><span>提示 {hint.hint_level}</span><p>{safeText(hint.safe_hint, "服务器已提供一条有界提示。")}</p></aside> : null}
      <div className="review-session-actions">
        {currentItem && currentItem.attempt?.status !== "terminal" ? <button className="tutor-compact-button quiet" type="button" disabled={busy !== null || (hint?.hint_level ?? 0) >= 3} onClick={() => void requestHint()}>{busy === "hint" ? "正在请求……" : "渐进提示"}</button> : null}
        {currentItem && !currentItem.attempt ? <button className="tutor-primary-button" type="button" disabled={busy !== null || !canSubmit(currentItem, submission, reviewDraft)} onClick={() => void submitAttempt()}>{busy === "attempt" ? "正在提交……" : "提交复习答案"}</button> : null}
        {currentItem?.attempt?.status === "pending" || latestAttempt?.status === "pending" ? <button className="tutor-primary-button" type="button" disabled={busy !== null} onClick={() => void pollCurrentAttempt()}>{busy === "poll" ? "正在刷新……" : "刷新同一 Attempt"}</button> : null}
        {session.state === "ready_to_finalize" ? <button className="tutor-primary-button" type="button" disabled={busy !== null} onClick={() => void finalize()}>{busy === "finalize" ? "正在完成……" : "完成本次复习"}</button> : null}
      </div>

      {referencedAttempt?.result ? (
        <section className={`review-result-card ${referencedAttempt.result.outcome}`} aria-live="polite">
          <div><span>本次结果</span><strong>{outcomeLabel(referencedAttempt.result.outcome)} · {Math.round(referencedAttempt.result.score * 100)}%</strong></div>
          <p>{safeText(referencedAttempt.result.safe_feedback, "服务器已记录本次复习结果。")}</p>
          <button className="tutor-compact-button quiet" type="button" onClick={() => onContextReference({ kind: "review_feedback", learning_track_id: track.track_id, knowledge_key: session.knowledge_key, review_session_id: session.session_id, attempt_id: referencedAttempt.attempt_id }, `复习反馈 · ${outcomeLabel(referencedAttempt.result?.outcome ?? "invalid")}`)}>引用给 Tutor</button>
        </section>
      ) : null}

      {session.state === "finalized" && session.finalization ? <section className="review-final-summary"><span>本次复习已完成</span><strong>{ratingLabel(session.finalization.rating)}</strong><p>调度结果已由服务器写入，下次到期时间不会由前端计算。</p></section> : null}
      {errorMessage ? <p className="lesson-gate-error" role="alert">{errorMessage}</p> : null}
    </section>
  );
}

function ReviewExerciseForm({ item, submission, reviewDraft, disabled, onSubmissionChange, onReviewDraftChange }: { item: ReviewSessionItem; submission: string; reviewDraft: ModelCodeReviewSubmission; disabled: boolean; onSubmissionChange: (value: string) => void; onReviewDraftChange: (draft: ModelCodeReviewSubmission) => void }) {
  const exercise = item.exercise;
  if (exercise.exercise_type !== "model_code_review") {
    return <div className="review-exercise"><div className="review-exercise-brief"><p>{safeText(exercise.learner_prompt, "请完成当前复习练习。")}</p><small>{exercise.execution_disclosure}</small></div><label><span>你的回答</span><textarea rows={Math.max(7, Math.min(16, submission.split("\n").length + 2))} value={submission} disabled={disabled} spellCheck={false} onChange={(event) => onSubmissionChange(event.target.value)} /></label></div>;
  }
  const artifact = exercise.starter_artifact;
  const errors = reviewSubmissionErrors(reviewDraft, artifact.line_count);
  const addFinding = () => onReviewDraftChange({ ...reviewDraft, findings: [...reviewDraft.findings, createFinding(artifact.line_count)] });
  return (
    <div className="review-exercise review-model-exercise">
      <div className="review-exercise-brief"><p>{exercise.learner_prompt.learner_instruction}</p><small>{exercise.execution_disclosure}</small></div>
      <figure className="model-review-code"><figcaption><span>{artifact.language_id}</span><strong>{artifact.runtime_label}</strong><small>{artifact.line_count} 行</small></figcaption><ol>{artifact.model_code.replace(/\r\n?/g, "\n").split("\n").map((line, index) => <li key={index}><code>{line || " "}</code></li>)}</ol></figure>
      <fieldset className="model-review-verdict" disabled={disabled}><legend>总体结论</legend>{VERDICTS.map((option) => <label key={option.value}><input type="radio" name={`review-verdict-${item.item_id}`} checked={reviewDraft.verdict === option.value} onChange={() => onReviewDraftChange({ ...reviewDraft, verdict: option.value })} /><span><strong>{option.label}</strong><small>{option.copy}</small></span></label>)}</fieldset>
      <div className="model-review-findings-heading"><div><strong>结构化发现</strong><span>记录触发条件、影响、验证方法与建议修复。</span></div><button className="tutor-compact-button quiet" type="button" disabled={disabled || reviewDraft.findings.length >= 12} onClick={addFinding}>添加发现</button></div>
      {reviewDraft.findings.map((finding, index) => <ModelCodeReviewFindingEditor key={finding.client_finding_id} finding={finding} index={index} lineCount={artifact.line_count} disabled={disabled} errors={validateFinding(finding, artifact.line_count)} onChange={(next) => onReviewDraftChange({ ...reviewDraft, findings: reviewDraft.findings.map((current, currentIndex) => currentIndex === index ? next : current) })} onRemove={() => onReviewDraftChange({ ...reviewDraft, findings: reviewDraft.findings.filter((_, currentIndex) => currentIndex !== index) })} />)}
      <label className="model-review-note"><span>总体补充说明（可选）</span><textarea rows={3} value={reviewDraft.supplemental_note ?? ""} disabled={disabled} onChange={(event) => onReviewDraftChange({ ...reviewDraft, supplemental_note: event.target.value || null })} /></label>
      {errors.length > 0 ? <ul className="model-review-form-errors" aria-live="polite">{errors.map((error) => <li key={error}>{error}</li>)}</ul> : null}
    </div>
  );
}

function ReviewStatus({ title, body, detail, actionLabel, onAction }: { title: string; body: string; detail?: string; actionLabel?: string; onAction?: () => void }) {
  return <section className="review-session-panel"><div className="review-status"><span aria-hidden="true">↺</span><div><p className="tutor-panel-eyebrow">ReviewSession</p><h1>{title}</h1><p>{body}</p>{detail ? <code>{detail}</code> : null}{actionLabel && onAction ? <button className="tutor-primary-button" type="button" onClick={onAction}>{actionLabel}</button> : null}</div></div></section>;
}

function terminalAttemptFromSession(session: ReviewSession): ReviewAttempt | null {
  const item = session.items.find((candidate) => candidate.attempt?.status === "terminal");
  return reviewAttemptFromSummary(session, item ?? null);
}
function reviewAttemptFromSummary(session: ReviewSession, item: ReviewSessionItem | null): ReviewAttempt | null {
  const attempt = item?.attempt;
  if (!item || !attempt) return null;
  return { attempt_id: attempt.attempt_id, attempt_type: "review_submit", track_id: session.track_id, session_id: session.session_id, item_id: item.item_id, knowledge_key: session.knowledge_key, session_version: session.version, exercise_version_id: item.exercise.exercise_version_id, submission_hash: item.exercise.content_hash, independence: attempt.independence, assistance_kind: attempt.assistance_kind, accepted_at: null, status: attempt.status, execution_job_id: attempt.execution_job_id, execution_job_state: attempt.execution_job_state, result: attempt.result, idempotent_replayed: false };
}
function starterText(item: ReviewSessionItem | null): string {
  if (!item || item.exercise.exercise_type === "model_code_review") return "";
  const value = item.exercise.starter_artifact.content;
  return typeof value === "string" ? value : "";
}
function safeText(payload: Record<string, unknown>, fallback: string): string { const value = payload.message ?? payload.text ?? payload.summary; return typeof value === "string" && value.trim() ? value : fallback; }
function canSubmit(item: ReviewSessionItem, submission: string, draft: ModelCodeReviewSubmission): boolean { return item.exercise.exercise_type === "model_code_review" ? reviewSubmissionErrors(draft, item.exercise.starter_artifact.line_count).length === 0 : submission.trim().length > 0; }
function emptyReviewDraft(): ModelCodeReviewSubmission { return { schema_version: "model_code_review_submission_v1", verdict: "uncertain", findings: [], supplemental_note: null }; }
function createFinding(lineCount: number): ModelReviewFinding { return { client_finding_id: `finding-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`}`, finding_kind: "correctness", start_line: 1, end_line: Math.min(1, lineCount), category: "correctness", severity: "medium", trigger_condition: "", principle: "", impact: "", validation_method: "", suggested_fix: "", supplemental_note: null }; }
function validateFinding(finding: ModelReviewFinding, lineCount: number): string[] { const errors: string[] = []; if (!Number.isInteger(finding.start_line) || finding.start_line < 1 || finding.start_line > lineCount) errors.push("起始行超出代码范围。"); if (!Number.isInteger(finding.end_line) || finding.end_line < finding.start_line || finding.end_line > lineCount) errors.push("结束行必须位于起始行之后且不超过代码范围。"); if (!/^[A-Za-z0-9][A-Za-z0-9._:@-]{0,119}$/.test(finding.category)) errors.push("分类键格式不合法。"); for (const [label, value] of [["触发条件", finding.trigger_condition], ["违反原则", finding.principle], ["可能影响", finding.impact], ["验证方法", finding.validation_method], ["建议修复", finding.suggested_fix]] as const) if (!value.trim()) errors.push(`${label}不能为空。`); if (finding.finding_kind === "improvement" && !["info", "low"].includes(finding.severity)) errors.push("改进建议的严重程度只能是提示或低。"); return errors; }
function reviewSubmissionErrors(draft: ModelCodeReviewSubmission, lineCount: number): string[] { const errors = draft.findings.flatMap((finding) => validateFinding(finding, lineCount)); const correctness = draft.findings.filter((item) => item.finding_kind === "correctness").length; const improvements = draft.findings.length - correctness; if (draft.verdict === "correctness_issue" && correctness === 0) errors.push("存在正确性问题时至少需要一条正确性发现。"); if (draft.verdict === "no_correctness_issue" && correctness > 0) errors.push("未发现正确性问题时不能包含正确性发现。"); if (draft.verdict === "improvement_only" && (improvements === 0 || correctness > 0)) errors.push("仅有改进建议时需要至少一条改进发现。"); return [...new Set(errors)]; }
function createReviewActionId(prefix: string): string { const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`; return `${prefix}:${random}`; }
function riskLabel(value: ReviewQueueItem["risk_level"]): string { return { low: "低", normal: "正常", high: "高", critical: "关键" }[value]; }
function confidenceLabel(value: "low" | "medium" | "high"): string { return { low: "不太熟", medium: "有印象", high: "比较熟" }[value]; }
function confidenceCopy(value: "low" | "medium" | "high"): string { return { low: "需要从最小规则开始", medium: "能回忆核心概念", high: "想直接检验细节" }[value]; }
function reviewStateLabel(value: ReviewSession["state"]): string { return { blocked: "受阻", active: "进行中", ready_to_finalize: "可完成", finalized: "已完成", cancelled: "已取消" }[value]; }
function outcomeLabel(value: NonNullable<ReviewAttempt["result"]>["outcome"]): string { return { passed: "通过", failed: "未通过", timed_out: "执行超时", cancelled: "已取消", unavailable: "执行不可用", invalid: "结果无效" }[value]; }
function ratingLabel(value: NonNullable<ReviewSession["finalization"]>["rating"]): string { return { again: "需要再次巩固", hard: "有些吃力", good: "掌握良好", easy: "轻松掌握" }[value]; }
const VERDICTS: Array<{ value: ModelReviewVerdict; label: string; copy: string }> = [
  { value: "correctness_issue", label: "存在正确性问题", copy: "至少记录一条 correctness finding。" },
  { value: "no_correctness_issue", label: "未发现正确性问题", copy: "可以保持 findings 为空。" },
  { value: "improvement_only", label: "仅有改进建议", copy: "至少记录一条 improvement finding。" },
  { value: "uncertain", label: "证据不足", copy: "明确当前不确定性。" },
];
