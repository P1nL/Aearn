import { useState } from "react";

import type { TutorPlanRevisionList, TutorPreferences } from "../../types";

type PreferenceUpdate = {
  inferredMemoryEnabled?: boolean;
  expectedMemorySettingVersion?: string;
  proactivePaused?: boolean;
};

type TutorPlanPreferencesPanelProps = {
  plans: TutorPlanRevisionList | null;
  preferences: TutorPreferences | null;
  loading: boolean;
  errorMessage: string | null;
  pendingAction: "rollback" | "memory" | "proactive" | null;
  onRetry: () => void;
  onRollback: () => Promise<void>;
  onUpdatePreferences: (update: PreferenceUpdate) => Promise<void>;
};

export function TutorPlanPreferencesPanel({
  plans,
  preferences,
  loading,
  errorMessage,
  pendingAction,
  onRetry,
  onRollback,
  onUpdatePreferences,
}: TutorPlanPreferencesPanelProps) {
  const [actionError, setActionError] = useState<string | null>(null);
  const activeRevision = plans?.items.find((item) => item.revision_id === plans.active_revision_id) ?? null;
  const canRollback = Boolean(activeRevision?.predecessor_revision_id);

  async function handleRollback() {
    setActionError(null);
    try {
      await onRollback();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "计划回退失败，请重试。");
    }
  }

  async function toggleInferredMemory() {
    if (!preferences) return;
    setActionError(null);
    try {
      await onUpdatePreferences({
        inferredMemoryEnabled: !preferences.inferred_memory_enabled,
        expectedMemorySettingVersion: preferences.memory_setting_version,
      });
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "学习记录偏好保存失败，请刷新后重试。");
    }
  }

  async function toggleProactivePause() {
    if (!preferences) return;
    setActionError(null);
    try {
      await onUpdatePreferences({ proactivePaused: !preferences.proactive_paused });
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "主动建议偏好保存失败，请重试。");
    }
  }

  return (
    <section className="tutor-panel tutor-plan-panel" aria-labelledby="tutor-plan-title">
      <div className="tutor-panel-heading">
        <div>
          <p className="tutor-panel-eyebrow">学习计划与偏好</p>
          <h2 id="tutor-plan-title">保持由你掌控</h2>
        </div>
        <button className="tutor-text-button" type="button" onClick={onRetry} disabled={loading}>刷新</button>
      </div>

      {errorMessage && (
        <div className="tutor-inline-error" role="alert">
          <span>{errorMessage}</span>
          <button className="tutor-text-button" type="button" onClick={onRetry}>重试</button>
        </div>
      )}
      {actionError && <p className="tutor-action-error" role="alert">{actionError}</p>}

      <section className="tutor-plan-section" aria-labelledby="tutor-plan-revision-title">
        <div className="tutor-subheading">
          <h3 id="tutor-plan-revision-title">计划版本</h3>
          <span>{plans?.items.length ?? 0} 个版本</span>
        </div>
        {loading && !plans && <p className="tutor-muted-copy">正在读取计划版本……</p>}
        {!loading && (!plans || plans.items.length === 0) && <p className="tutor-muted-copy">Tutor 还没有创建可展示的学习计划版本。</p>}
        {plans?.items.map((revision) => {
          const isActive = revision.revision_id === plans.active_revision_id;
          return (
            <article className={`tutor-plan-revision ${isActive ? "active" : ""}`} key={revision.revision_id}>
              <div className="tutor-plan-revision-heading">
                <strong>{revision.title}</strong>
                {isActive && <span className="tutor-state-label accent">当前版本</span>}
              </div>
              <p>{revision.learner_reason}</p>
              {revision.outline.length > 0 && <ul>{revision.outline.map((item) => <li key={item}>{item}</li>)}</ul>}
              {revision.diff.length > 0 && <div className="tutor-plan-diff"><span>本次调整</span><ul>{revision.diff.map((item) => <li key={item}>{item}</li>)}</ul></div>}
              <p className="tutor-plan-evidence">依据：{revision.evidence.length > 0 ? revision.evidence.join(" · ") : "暂无可展示依据"}</p>
              <span className="tutor-plan-time">{formatTutorTime(revision.created_at)}</span>
            </article>
          );
        })}
        <button className="tutor-compact-button" type="button" disabled={!canRollback || pendingAction === "rollback"} onClick={() => void handleRollback()}>
          {pendingAction === "rollback" ? "正在回退……" : "回退到上个版本"}
        </button>
        {!canRollback && activeRevision && <p className="tutor-muted-copy">当前版本没有可回退的前一版本。</p>}
      </section>

      <section className="tutor-plan-section" aria-labelledby="tutor-preference-title">
        <div className="tutor-subheading"><h3 id="tutor-preference-title">学习偏好</h3></div>
        {loading && !preferences && <p className="tutor-muted-copy">正在读取偏好设置……</p>}
        {!loading && !preferences && <p className="tutor-muted-copy">偏好设置暂不可用。</p>}
        {preferences && (
          <div className="tutor-preference-list">
            <label className="tutor-toggle-row">
              <input
                type="checkbox"
                checked={preferences.inferred_memory_enabled}
                disabled={pendingAction === "memory"}
                onChange={() => void toggleInferredMemory()}
              />
              <span>
                <strong>允许保存学习推断</strong>
                <small>关闭后，不会再保存基于学习过程推断出的长期记录。</small>
              </span>
            </label>
            <label className="tutor-toggle-row">
              <input
                type="checkbox"
                checked={preferences.proactive_paused}
                disabled={!preferences.proactive_enabled || pendingAction === "proactive"}
                onChange={() => void toggleProactivePause()}
              />
              <span>
                <strong>暂停主动建议</strong>
                <small>{preferences.proactive_enabled ? "暂停后，系统不会主动生成新的学习建议。" : "主动建议尚未对当前学习流程开放。"}</small>
              </span>
            </label>
          </div>
        )}
      </section>
    </section>
  );
}

function formatTutorTime(value: string | null): string {
  if (!value) return "时间待同步";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { year: "numeric", month: "numeric", day: "numeric" });
}
