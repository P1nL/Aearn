import type { SSEPlanDraft } from "../hooks/useSSE";

type InlinePlanCardProps = {
  draft: SSEPlanDraft;
  confirming: boolean;
  onConfirm: () => void;
  onRevise: () => void;
};

/**
 * Renders a plan draft as an inline card within the conversation thread.
 * Shows module structure and provides confirm/revise actions.
 */
export function InlinePlanCard({ draft, confirming, onConfirm, onRevise }: InlinePlanCardProps) {
  return (
    <article className="inline-plan-card" aria-label="学习计划草稿">
      <header className="inline-plan-card-header">
        <span className="inline-plan-card-kicker">学习计划草稿</span>
        <span className="inline-plan-card-id">{draft.draft_id.slice(0, 8)}</span>
      </header>

      {draft.summary && <p className="inline-plan-card-summary">{draft.summary}</p>}

      <div className="inline-plan-card-modules">
        {draft.modules.map((module, index) => (
          <div className="inline-plan-card-module" key={`${module.title}-${index}`}>
            <span className="inline-plan-card-module-index">{index + 1}</span>
            <div className="inline-plan-card-module-body">
              <strong>{module.title}</strong>
              {module.knowledge_points.length > 0 && (
                <span className="inline-plan-card-kp-count">
                  {module.knowledge_points.length} 个知识点
                </span>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="inline-plan-card-actions">
        <button
          className="btn primary"
          type="button"
          disabled={confirming}
          onClick={onConfirm}
        >
          {confirming ? "确认中..." : "确认学习计划"}
        </button>
        <button
          className="btn ghost"
          type="button"
          disabled={confirming}
          onClick={onRevise}
        >
          我想调整
        </button>
      </div>
    </article>
  );
}
