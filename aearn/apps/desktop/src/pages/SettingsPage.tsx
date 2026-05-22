import type { SettingsKey } from "../appTypes";
import { SETTING_PANELS } from "../lib/appContent";

type SettingsFormValue = {
  displayName: string;
  learningStyle: string;
  teachingPreference: string;
  encouragementPreference: string;
  profession: string;
  backgroundContext: string;
  preferredWeekday: string;
  preferredStart: string;
  preferredEnd: string;
  reminderEnabled: boolean;
  reminderChannel: string;
  quietHoursStart: string;
  quietHoursEnd: string;
};

type SettingsPageProps = {
  settingsTab: SettingsKey;
  form: SettingsFormValue;
  isDirty: boolean;
  canSave: boolean;
  saveState: "idle" | "saving" | "saved" | "error";
  saveErrorMessage: string | null;
  userLoaded: boolean;
  diagnostics: {
    apiBaseUrl: string;
    apiStatus: string;
    userId: string | null;
    planId: string | null;
    currentStage: string | null;
    todayReviewCount: number;
    resumeAvailable: boolean;
  };
  onSettingsTabChange: (value: SettingsKey) => void;
  onFieldChange: (field: keyof SettingsFormValue, value: string | boolean) => void;
  onSave: () => void;
};

export function SettingsPage({
  settingsTab,
  form,
  isDirty,
  canSave,
  saveState,
  saveErrorMessage,
  userLoaded,
  diagnostics,
  onSettingsTabChange,
  onFieldChange,
  onSave,
}: SettingsPageProps) {
  const currentSettingsPanel = SETTING_PANELS[settingsTab];
  const editableTab = settingsTab === "learning" || settingsTab === "notifications";

  return (
    <div className="settings-screen">
      <div className="kicker">Settings</div>
      <p>管理你的学习偏好和通知设置。</p>

      <div className="settings-tabs" role="tablist" aria-label="设置分类">
        {Object.entries(SETTING_PANELS).map(([key, panel]) => (
          <button
            className={settingsTab === key ? "settings-tab active" : "settings-tab"}
            key={key}
            role="tab"
            aria-selected={settingsTab === key}
            tabIndex={settingsTab === key ? 0 : -1}
            type="button"
            onClick={() => onSettingsTabChange(key as SettingsKey)}
          >
            {panel.title}
          </button>
        ))}
      </div>

      <div className="settings-content">
        <section className="panel pad stack">
          <div className="panel-head">
            <div>
              <h2>{currentSettingsPanel.title}</h2>
              <span className="meta">{currentSettingsPanel.meta}</span>
            </div>
            <div className="settings-action-bar">
              <span className={`settings-status settings-status-${saveState}`}>
                {saveStateLabel(saveState, isDirty, editableTab)}
              </span>
              <button className="btn primary" type="button" disabled={!canSave} onClick={onSave}>
                {saveState === "saving" ? "保存中..." : editableTab ? "保存设置" : "当前分类只读"}
              </button>
            </div>
          </div>

          {saveErrorMessage && <div className="tool-card settings-callout error">错误：{saveErrorMessage}</div>}
          {!userLoaded && editableTab && <div className="tool-card settings-callout">先完成建档并加载用户资料后，才会启用可保存设置。</div>}

          {renderPanel(settingsTab, form, diagnostics, onFieldChange)}
        </section>

        <aside className="panel pad stack">
          <h2>当前配置摘要</h2>
          <div className="settings-mini active">
            <h3 className="mini-title">学习偏好</h3>
            <p className="mini-body">
              {compactValue(form.learningStyle, "先练后学")} / {compactValue(form.teachingPreference, "逐步讲解")} /{" "}
              {compactValue(form.encouragementPreference, "直接反馈")}
            </p>
          </div>
          <div className="settings-mini">
            <h3 className="mini-title">提醒策略</h3>
            <p className="mini-body">
              {form.reminderEnabled ? `已启用 · 安静时段 ${form.quietHoursStart}-${form.quietHoursEnd}` : "提醒已关闭"}
            </p>
          </div>
          <div className="settings-mini">
            <h3 className="mini-title">学习状态</h3>
            <p className="mini-body">
              {diagnostics.resumeAvailable ? `可继续上次学习 · 今日待复习 ${diagnostics.todayReviewCount}` : `今日待复习 ${diagnostics.todayReviewCount}`}
            </p>
          </div>
          <div className="settings-mini">
            <h3 className="mini-title">连接状态</h3>
            <p className="mini-body">
              {diagnostics.apiStatus === "ok" ? "服务正常" : "服务异常"} · {diagnostics.userId ? "已登录" : "未登录"}
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}

function renderPanel(
  settingsTab: SettingsKey,
  form: SettingsFormValue,
  diagnostics: SettingsPageProps["diagnostics"],
  onFieldChange: SettingsPageProps["onFieldChange"],
) {
  if (settingsTab === "learning") {
    return (
      <div className="settings-form-grid">
        <label className="inline-field">
          <span>显示名称</span>
          <input value={form.displayName} onChange={(event) => onFieldChange("displayName", event.target.value)} />
        </label>
        <label className="inline-field">
          <span>学习风格</span>
          <input value={form.learningStyle} onChange={(event) => onFieldChange("learningStyle", event.target.value)} />
        </label>
        <label className="inline-field">
          <span>讲解偏好</span>
          <input value={form.teachingPreference} onChange={(event) => onFieldChange("teachingPreference", event.target.value)} />
        </label>
        <label className="inline-field">
          <span>鼓励偏好</span>
          <input value={form.encouragementPreference} onChange={(event) => onFieldChange("encouragementPreference", event.target.value)} />
        </label>
        <label className="inline-field">
          <span>职业背景</span>
          <input value={form.profession} onChange={(event) => onFieldChange("profession", event.target.value)} />
        </label>
        <label className="inline-field settings-span-2">
          <span>编程背景</span>
          <textarea value={form.backgroundContext} onChange={(event) => onFieldChange("backgroundContext", event.target.value)} />
        </label>
      </div>
    );
  }

  if (settingsTab === "notifications") {
    return (
      <div className="settings-form-grid">
        <label className="settings-toggle">
          <span>启用提醒</span>
          <input
            checked={form.reminderEnabled}
            type="checkbox"
            onChange={(event) => onFieldChange("reminderEnabled", event.target.checked)}
          />
        </label>
        <label className="inline-field">
          <span>提醒渠道</span>
          <input value={form.reminderChannel} onChange={(event) => onFieldChange("reminderChannel", event.target.value)} />
        </label>
        <label className="inline-field">
          <span>偏好星期</span>
          <input value={form.preferredWeekday} onChange={(event) => onFieldChange("preferredWeekday", event.target.value)} />
        </label>
        <label className="inline-field">
          <span>开始时间</span>
          <input value={form.preferredStart} onChange={(event) => onFieldChange("preferredStart", event.target.value)} />
        </label>
        <label className="inline-field">
          <span>结束时间</span>
          <input value={form.preferredEnd} onChange={(event) => onFieldChange("preferredEnd", event.target.value)} />
        </label>
        <label className="inline-field">
          <span>安静时段开始</span>
          <input value={form.quietHoursStart} onChange={(event) => onFieldChange("quietHoursStart", event.target.value)} />
        </label>
        <label className="inline-field">
          <span>安静时段结束</span>
          <input value={form.quietHoursEnd} onChange={(event) => onFieldChange("quietHoursEnd", event.target.value)} />
        </label>
      </div>
    );
  }

  if (settingsTab === "review") {
    return (
      <div className="settings-grid">
        <article className="setting-card">
          <h3>高风险优先</h3>
          <p>中断学习超过 72 小时且存在高遗忘风险时，首页会优先引导你进入复习。</p>
        </article>
        <article className="setting-card">
          <h3>普通打开</h3>
          <p>有待复习内容时只在应用内提示，不会强制跳转。</p>
        </article>
        <article className="setting-card">
          <h3>今日复习</h3>
          <p>当前待复习：{diagnostics.todayReviewCount} 项</p>
        </article>
        <article className="setting-card">
          <h3>自动调度</h3>
          <p>复习时间和遗忘风险由系统自动计算和更新，无需手动设置。</p>
        </article>
      </div>
    );
  }

  if (settingsTab === "diagnostics") {
    return (
      <div className="settings-grid">
        <article className="setting-card">
          <h3>API base URL</h3>
          <p>{diagnostics.apiBaseUrl}</p>
        </article>
        <article className="setting-card">
          <h3>API 状态</h3>
          <p>{diagnostics.apiStatus}</p>
        </article>
        <article className="setting-card">
          <h3>当前用户</h3>
          <p>{diagnostics.userId ?? "未识别"}</p>
        </article>
        <article className="setting-card">
          <h3>活动计划</h3>
          <p>{diagnostics.planId ?? "未识别"}</p>
        </article>
        <article className="setting-card">
          <h3>当前阶段</h3>
          <p>{diagnostics.currentStage ?? "暂无阶段"}</p>
        </article>
        <article className="setting-card">
          <h3>恢复状态</h3>
          <p>{diagnostics.resumeAvailable ? "可恢复当前学习" : "暂无可恢复上下文"}</p>
        </article>
      </div>
    );
  }

  return (
    <div className="settings-grid">
      {SETTING_PANELS[settingsTab].cards.map(([title, body]) => (
        <article className="setting-card" key={`${settingsTab}-${title}`}>
          <h3>{title}</h3>
          <p>{body}</p>
        </article>
      ))}
    </div>
  );
}

function saveStateLabel(
  value: SettingsPageProps["saveState"],
  isDirty: boolean,
  editableTab: boolean,
) {
  if (!editableTab) {
    return "只读说明";
  }
  if (value === "saving") {
    return "保存中";
  }
  if (value === "saved") {
    return "已保存";
  }
  if (value === "error") {
    return "保存失败";
  }
  return isDirty ? "有未保存更改" : "等待修改";
}

function compactValue(value: string, fallback: string) {
  return value.trim() ? value : fallback;
}
