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
      <p>设置页保留七个分类；只有当前后端 contract 支持的字段会真正保存，其余分类显示边界说明和诊断信息。</p>

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
              {compactValue(form.learningStyle, "practice_first")} / {compactValue(form.teachingPreference, "step_by_step")} /{" "}
              {compactValue(form.encouragementPreference, "direct")}
            </p>
          </div>
          <div className="settings-mini">
            <h3 className="mini-title">提醒策略</h3>
            <p className="mini-body">
              {form.reminderEnabled ? `启用 ${form.reminderChannel || "desktop"} · ${form.quietHoursStart}-${form.quietHoursEnd}` : "提醒关闭"}
            </p>
          </div>
          <div className="settings-mini">
            <h3 className="mini-title">恢复状态</h3>
            <p className="mini-body">
              {diagnostics.resumeAvailable ? `可恢复 · 今日复习 ${diagnostics.todayReviewCount}` : `不可恢复 · 今日复习 ${diagnostics.todayReviewCount}`}
            </p>
          </div>
          <div className="settings-mini">
            <h3 className="mini-title">诊断</h3>
            <p className="mini-body">
              API {diagnostics.apiStatus} · {diagnostics.currentStage ?? "暂无阶段"} · {diagnostics.userId ? "已识别用户" : "未识别用户"}
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
          <h3>高风险优先条件</h3>
          <p>最近学习活动超过 72 小时，且存在至少一条 `forget_risk = high` 的到期复习时，首页优先进入复习页。</p>
        </article>
        <article className="setting-card">
          <h3>普通打开规则</h3>
          <p>只要没有同时满足“中断多日 + 高风险”，桌面端仍默认进入当前学习，并在应用内提示今日复习数量。</p>
        </article>
        <article className="setting-card">
          <h3>今日复习摘要</h3>
          <p>当前后端返回的到期复习数：{diagnostics.todayReviewCount}。</p>
        </article>
        <article className="setting-card">
          <h3>固定规则</h3>
          <p>FSRS rating、`due_at`、`forget_risk` 和 ReviewState 仍由后端负责，设置页不提供直接编辑。</p>
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
