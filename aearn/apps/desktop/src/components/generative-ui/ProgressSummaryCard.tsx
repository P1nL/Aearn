import type { ToolUIProps, ProgressSummaryArgs } from "./types";

export function ProgressSummaryCard({ args, status, onAction }: ToolUIProps<ProgressSummaryArgs>) {
  const progressPct = Math.round(args.overall_progress * 100);

  return (
    <article className="gen-card gen-progress-card" aria-label="学习进度">
      <header className="gen-card-header">
        <span className="gen-card-kicker">学习进度</span>
        {args.streak_days > 0 && (
          <span className="gen-card-badge">连续 {args.streak_days} 天</span>
        )}
      </header>

      <div className="gen-progress-ring-row">
        <div className="gen-progress-ring" style={{ "--progress-pct": `${progressPct}%` } as React.CSSProperties}>
          <span className="gen-progress-ring-value">{progressPct}%</span>
        </div>
        <div className="gen-progress-stats">
          <div className="gen-progress-stat">
            <span className="gen-progress-stat-value">{args.modules_completed}/{args.modules_total}</span>
            <span className="gen-progress-stat-label">模块完成</span>
          </div>
          <div className="gen-progress-stat">
            <span className="gen-progress-stat-value">{args.points_mastered}/{args.points_total}</span>
            <span className="gen-progress-stat-label">知识点掌握</span>
          </div>
          <div className="gen-progress-stat">
            <span className="gen-progress-stat-value">{args.today_sessions}</span>
            <span className="gen-progress-stat-label">今日学习</span>
          </div>
        </div>
      </div>

      {args.next_review_at && (
        <div className="gen-progress-next-review">
          下次复习：{formatDate(args.next_review_at)}
        </div>
      )}

      {status === "done" && (
        <div className="gen-card-actions">
          <button className="btn primary" type="button" onClick={() => onAction?.("continue", { next_action: args.next_action })}>
            继续学习
          </button>
          <button className="btn ghost" type="button" onClick={() => onAction?.("view_details")}>
            查看详情
          </button>
        </div>
      )}
    </article>
  );
}

function formatDate(iso: string): string {
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}
