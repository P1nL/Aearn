import type { ToolUIProps, LearningRouteArgs } from "./types";

export function LearningRouteCard({ args, status, onAction }: ToolUIProps<LearningRouteArgs>) {
  const completedModules = args.modules.filter((m) => m.status === "completed").length;
  const totalPoints = args.modules.reduce((sum, m) => sum + m.knowledge_points.length, 0);
  const masteredPoints = args.modules.reduce(
    (sum, m) => sum + m.knowledge_points.filter((kp) => kp.status === "mastered").length,
    0,
  );

  return (
    <article className="gen-card gen-route-card" aria-label="学习路线">
      <header className="gen-card-header">
        <span className="gen-card-kicker">学习路线</span>
        {status === "running" && <span className="gen-card-badge streaming">生成中…</span>}
        {status === "done" && (
          <span className="gen-card-badge">
            {completedModules}/{args.modules.length} 模块
          </span>
        )}
      </header>

      <h3 className="gen-card-title">{args.goal_text}</h3>

      <div className="gen-route-progress">
        <div className="gen-route-progress-bar">
          <div
            className="gen-route-progress-fill"
            style={{ width: `${totalPoints > 0 ? (masteredPoints / totalPoints) * 100 : 0}%` }}
          />
        </div>
        <span className="gen-route-progress-label">
          {masteredPoints}/{totalPoints} 知识点已掌握
        </span>
      </div>

      <div className="gen-route-modules">
        {args.modules.map((module) => (
          <div
            className={`gen-route-module ${module.status}`}
            key={module.id}
            role="button"
            tabIndex={0}
            onClick={() => onAction?.("select_module", { module_id: module.id })}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") onAction?.("select_module", { module_id: module.id });
            }}
          >
            <div className="gen-route-module-indicator">
              {module.status === "completed" ? "✓" : module.status === "in_progress" ? "●" : module.order_index + 1}
            </div>
            <div className="gen-route-module-body">
              <strong>{module.title}</strong>
              <span className="gen-route-module-meta">
                {module.knowledge_points.length} 知识点 · 约 {module.estimated_sessions} 次学习
              </span>
              {module.status === "in_progress" && (
                <div className="gen-route-kp-list">
                  {module.knowledge_points.slice(0, 4).map((kp) => (
                    <span className={`gen-route-kp ${kp.status}`} key={kp.id}>
                      {kp.title}
                    </span>
                  ))}
                  {module.knowledge_points.length > 4 && (
                    <span className="gen-route-kp-more">+{module.knowledge_points.length - 4}</span>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {status === "done" && (
        <div className="gen-card-actions">
          <button className="btn primary" type="button" onClick={() => onAction?.("start_next")}>
            继续学习
          </button>
          <button className="btn ghost" type="button" onClick={() => onAction?.("adjust_plan")}>
            调整计划
          </button>
        </div>
      )}
    </article>
  );
}
