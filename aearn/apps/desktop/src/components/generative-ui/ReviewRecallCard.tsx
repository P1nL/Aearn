import type { ToolUIProps, ReviewRecallArgs } from "./types";

export function ReviewRecallCard({ args, status, onAction }: ToolUIProps<ReviewRecallArgs>) {
  return (
    <article className="gen-card gen-recall-card" aria-label="回忆检查">
      <header className="gen-card-header">
        <span className="gen-card-kicker">回忆检查</span>
        <span className={`gen-card-badge ${args.forget_risk}`}>{riskLabel(args.forget_risk)}</span>
      </header>

      <h3 className="gen-card-title">{args.knowledge_point_title}</h3>
      {args.description && <p className="gen-recall-desc">{args.description}</p>}

      <div className="gen-recall-meta">
        {args.last_review_at && (
          <span>上次复习：{formatDate(args.last_review_at)}</span>
        )}
        <span>已复习 {args.review_count} 次</span>
      </div>

      {args.weak_points.length > 0 && (
        <div className="gen-recall-weak">
          <span className="gen-recall-weak-label">重点关注</span>
          <div className="gen-recall-weak-tags">
            {args.weak_points.map((wp) => (
              <span className="gen-recall-weak-tag" key={wp}>{wp}</span>
            ))}
          </div>
        </div>
      )}

      {status === "done" && (
        <div className="gen-card-actions">
          <button className="btn primary" type="button" onClick={() => onAction?.("recall_confident")}>
            我记得
          </button>
          <button className="btn ghost" type="button" onClick={() => onAction?.("recall_uncertain")}>
            不太确定
          </button>
          <button className="btn ghost" type="button" onClick={() => onAction?.("recall_forgot")}>
            完全忘了
          </button>
        </div>
      )}
    </article>
  );
}

function riskLabel(risk: string): string {
  switch (risk) {
    case "high": return "高遗忘风险";
    case "normal": return "正常";
    case "low": return "低风险";
    default: return risk;
  }
}

function formatDate(iso: string): string {
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}
