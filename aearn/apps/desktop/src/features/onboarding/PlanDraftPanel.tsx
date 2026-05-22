import type { AsyncActionState } from "../../appTypes";
import type { LanguageCourse, PlanDraft } from "../../types";
import { runtimeLabel } from "../../lib/desktopLabels";
import { buildFallbackDraftModules, mapDraftModuleCard } from "../../lib/learningHelpers";

type PlanDraftPanelProps = {
  actionState: AsyncActionState;
  planDraft: PlanDraft | null;
  selectedCourse: LanguageCourse | null;
  isBusy: boolean;
  onConfirm: () => void;
};

export function PlanDraftPanel({
  actionState,
  planDraft,
  selectedCourse,
  isBusy,
  onConfirm,
}: PlanDraftPanelProps) {
  const modules = planDraft ? planDraft.modules.map(mapDraftModuleCard) : buildFallbackDraftModules();

  return (
    <div className="stack">
      <div>
        <div className="kicker">学习计划草稿</div>
        <p>确认后即可开始学习。</p>
      </div>

      {selectedCourse && (
        <div className="draft-summary">
          <strong>{selectedCourse.title}</strong>
          <span>{runtimeLabel(selectedCourse.runtime_profile.runtime_tier)}</span>
        </div>
      )}

      {actionState.status === "loading" && <div className="tool-card">{actionState.label}</div>}
      {actionState.status === "error" && (
        <article className="review-mini active error-card">
          <h3 className="mini-title">
            {actionState.code} {actionState.recoverable ? "可重试" : "需修复"}
          </h3>
          <p className="mini-body">{actionState.message}</p>
        </article>
      )}

      <div className="draft-route">
        {modules.map((module, index) => (
          <article className={index === 0 ? "draft-module active" : "draft-module"} key={module.id}>
            <span className="module-index">{index + 1}</span>
            <div>
              <h3>{module.title}</h3>
              <span className="meta">{module.description}</span>
            </div>
            <span className={module.tagClass}>{module.tag}</span>
          </article>
        ))}
      </div>

      {planDraft && (
        <>
          <div className="draft-boundary">{planDraft.runtime_boundary.notice}</div>
          <div className="source-strip">
            {planDraft.source_attribution.map((source) => (
              <span key={source}>{source}</span>
            ))}
          </div>
          <button className="btn primary confirm-draft-btn" type="button" disabled={isBusy} onClick={onConfirm}>
            确认学习计划并进入会话
          </button>
        </>
      )}
    </div>
  );
}
