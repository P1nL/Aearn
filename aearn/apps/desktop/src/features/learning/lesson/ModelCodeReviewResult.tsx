import type { LessonGateResult, ModelReviewSafeFeedback } from "../../../types";

type ModelCodeReviewResultProps = { result: LessonGateResult & { safe_feedback: ModelReviewSafeFeedback }; stale: boolean; historyOnly: boolean };

export function ModelCodeReviewResult({ result, stale, historyOnly }: ModelCodeReviewResultProps) {
  const feedback = result.safe_feedback;
  return (
    <section className={`model-review-result ${result.outcome}`} aria-live="polite">
      <header>
        <div><span>{stale ? (historyOnly ? "历史审核" : "结果已过期") : "当前审核"}</span><strong>{outcomeLabel(result.outcome)} · {Math.round(result.score * 100)}%</strong></div>
        <span className="model-review-assisted">{assistanceLabel(feedback.assistance_kind)}</span>
      </header>
      <p>{feedback.message}</p>
      <dl className="model-review-score-grid">
        <Score label="结论" value={feedback.score_breakdown.verdict} />
        <Score label="发现" value={feedback.score_breakdown.discovery} />
        <Score label="遗漏控制" value={feedback.score_breakdown.omission} />
        <Score label="证据" value={feedback.score_breakdown.evidence} />
        <Score label="验证" value={feedback.score_breakdown.validation_method} />
        <Score label="修复" value={feedback.score_breakdown.suggested_fix} />
      </dl>
      {feedback.finding_feedback.length > 0 ? (
        <ul className="model-review-feedback-list">
          {feedback.finding_feedback.map((item) => (
            <li key={item.client_finding_id}>
              <strong>{item.client_finding_id}</strong>
              <span data-status={item.status}>{findingStatusLabel(item.status)}</span>
              <small>{safeReasonLabel(item.safe_reason_code)}</small>
            </li>
          ))}
        </ul>
      ) : <p className="model-review-empty-feedback">本次提交没有逐条 finding 反馈。</p>}
      <footer>遗漏范围：{omissionLabel(feedback.omission_band)} · 下一步：{nextActionLabel(feedback.next_action)}</footer>
      {stale ? <p className="lesson-gate-stale">审核草稿已经变化，或这是服务器保存的上一份结果；请勿把它当作当前草稿的评估。</p> : null}
    </section>
  );
}

function Score({ label, value }: { label: string; value: number }) {
  return <div><dt>{label}</dt><dd>{Math.round(value * 100)}%</dd></div>;
}
function outcomeLabel(value: LessonGateResult["outcome"]): string {
  return { passed: "通过", failed: "未通过", timed_out: "超时", cancelled: "已取消", unavailable: "不可用", invalid: "无效" }[value];
}
function assistanceLabel(value: ModelReviewSafeFeedback["assistance_kind"]): string {
  return { independent: "独立完成", hinted: "使用提示", validation_evidence_viewed: "已查看验证证据", remediated: "补救后完成" }[value];
}
function findingStatusLabel(value: ModelReviewSafeFeedback["finding_feedback"][number]["status"]): string {
  return { supported: "已支持", partial: "部分支持", unsupported: "未支持", duplicate: "重复" }[value];
}
function omissionLabel(value: ModelReviewSafeFeedback["omission_band"]): string {
  return { none: "无明显遗漏", limited: "存在有限遗漏", major: "存在重大遗漏" }[value];
}
function nextActionLabel(value: ModelReviewSafeFeedback["next_action"]): string {
  return { advance_next: "进入下一项", review_variant: "审核变体", show_hint: "查看提示" }[value];
}
function safeReasonLabel(value: string): string {
  const labels: Record<string, string> = { exact_match: "证据与预期问题一致", partial_match: "方向接近但证据不完整", false_positive: "当前证据不足以支持该问题", duplicate_finding: "与另一条发现重复" };
  return labels[value] ?? value.replaceAll("_", " ");
}
