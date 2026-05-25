import type { ToolUIProps, SubmitResultArgs } from "./types";

export function SubmitResultCard({ args, status, onAction }: ToolUIProps<SubmitResultArgs>) {
  const resultColor = args.result === "passed" || args.result === "easy"
    ? "var(--success)"
    : args.result === "partial"
      ? "var(--warning)"
      : "var(--danger)";

  return (
    <article className="gen-card gen-result-card" aria-label="提交结果">
      <header className="gen-card-header">
        <span className="gen-card-kicker">练习结果</span>
        <span className="gen-card-badge" style={{ color: resultColor }}>
          {resultLabel(args.result)}
        </span>
      </header>

      <div className="gen-result-score">
        <div className="gen-result-score-ring" style={{ "--score-pct": `${args.score}%` } as React.CSSProperties}>
          <span className="gen-result-score-value">{args.score}</span>
        </div>
        <div className="gen-result-score-detail">
          <span>FSRS 评级：{fsrsLabel(args.fsrs_rating)}</span>
          <p className="gen-result-feedback">{args.feedback}</p>
        </div>
      </div>

      <div className="gen-result-breakdown">
        <ScoreBar label="补全正确性" value={args.score_breakdown.completion_correctness} />
        <ScoreBar label="运行与测试" value={args.score_breakdown.runtime_and_tests} />
        <ScoreBar label="错误诊断" value={args.score_breakdown.error_diagnosis} />
        <ScoreBar label="解释检查" value={args.score_breakdown.explanation_check} />
      </div>

      {args.weak_points.length > 0 && (
        <div className="gen-result-weak">
          <span className="gen-result-weak-label">薄弱点</span>
          <div className="gen-result-weak-tags">
            {args.weak_points.map((wp) => (
              <span className="gen-result-weak-tag" key={wp}>{wp}</span>
            ))}
          </div>
        </div>
      )}

      {status === "done" && (
        <div className="gen-card-actions">
          <button className="btn primary" type="button" onClick={() => onAction?.("next", { next_action: args.next_action })}>
            {nextActionLabel(args.next_action)}
          </button>
        </div>
      )}
    </article>
  );
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="gen-result-bar">
      <span className="gen-result-bar-label">{label}</span>
      <div className="gen-result-bar-track">
        <div className="gen-result-bar-fill" style={{ width: `${value * 100}%` }} />
      </div>
      <span className="gen-result-bar-value">{Math.round(value * 100)}</span>
    </div>
  );
}

function resultLabel(result: SubmitResultArgs["result"]): string {
  switch (result) {
    case "easy": return "轻松掌握";
    case "passed": return "通过";
    case "partial": return "部分通过";
    case "failed": return "未通过";
  }
}

function fsrsLabel(rating: string): string {
  switch (rating) {
    case "Again": return "需要重学";
    case "Hard": return "较困难";
    case "Good": return "良好";
    case "Easy": return "轻松";
    default: return rating;
  }
}

function nextActionLabel(action: string): string {
  switch (action) {
    case "advance_next": return "继续下一步";
    case "retry_same": return "重新尝试";
    case "show_hint": return "获取提示";
    case "explain_error": return "解释错误";
    case "review_variant": return "复习变体";
    case "schedule_review": return "安排复习";
    default: return "继续";
  }
}
