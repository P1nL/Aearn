import type { ToolUIProps, SubmitResultArgs } from "./types";
import { completionResultLabel, fsrsRatingLabel, nextActionLabel } from "../../lib/desktopLabels";

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
          {completionResultLabel(args.result)}
        </span>
      </header>

      <div className="gen-result-score">
        <div className="gen-result-score-ring" style={{ "--score-pct": `${args.score}%` } as React.CSSProperties}>
          <span className="gen-result-score-value">{args.score}</span>
        </div>
        <div className="gen-result-score-detail">
          <span>掌握程度：{fsrsRatingLabel(args.fsrs_rating)}</span>
          <p className="gen-result-feedback">{args.feedback}</p>
        </div>
      </div>

      <div className="gen-result-breakdown">
        <ScoreBar label="补全正确性" value={args.score_breakdown.completion_correctness ?? args.score_breakdown.verdict_correctness ?? 0} />
        <ScoreBar label="运行与测试" value={args.score_breakdown.runtime_and_tests ?? args.score_breakdown.evidence_grounding ?? 0} />
        <ScoreBar label="错误诊断" value={args.score_breakdown.error_diagnosis ?? args.score_breakdown.knowledge_point_alignment ?? 0} />
        <ScoreBar label="解释检查" value={args.score_breakdown.explanation_check ?? args.score_breakdown.actionability ?? 0} />
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
