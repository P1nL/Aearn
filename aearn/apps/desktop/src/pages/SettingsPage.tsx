import type { SettingsKey, SettingsPanel } from "../appTypes";
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
  const currentPanel = SETTING_PANELS[settingsTab];
  const editableTab = settingsTab === "learning" || settingsTab === "notifications";

  return (
    <div className="settings-screen">
      <header className="settings-header">
        <div>
          <h2>设置</h2>
          <p className="meta">{currentPanel.meta}</p>
        </div>
        {editableTab && (
          <div className="settings-action-bar">
            <span className={`settings-status settings-status-${saveState}`}>
              {saveStateLabel(saveState, isDirty)}
            </span>
            <button className="btn primary" type="button" disabled={!canSave} onClick={onSave}>
              {saveState === "saving" ? "保存中..." : "保存"}
            </button>
          </div>
        )}
      </header>

      <nav className="settings-tabs" role="tablist" aria-label="设置分类">
        {Object.entries(SETTING_PANELS).map(([key, panel]) => (
          <button
            className={settingsTab === key ? "settings-tab active" : "settings-tab"}
            key={key}
            role="tab"
            aria-selected={settingsTab === key}
            type="button"
            onClick={() => onSettingsTabChange(key as SettingsKey)}
          >
            {panel.title}
          </button>
        ))}
      </nav>

      {saveErrorMessage && <div className="tool-card settings-callout error">错误：{saveErrorMessage}</div>}
      {!userLoaded && editableTab && (
        <div className="tool-card settings-callout">先完成建档并加载用户资料后，才能保存设置。</div>
      )}

      <section className="settings-body">
        {settingsTab === "appearance" && renderReadOnlyPanel(currentPanel)}
        {settingsTab === "models" && renderModelPanel(currentPanel, diagnostics)}
        {settingsTab === "learning" && renderLearningPanel(form, onFieldChange)}
        {settingsTab === "review" && renderReviewPanel(currentPanel)}
        {settingsTab === "notifications" && renderNotificationsPanel(form, onFieldChange)}
        {settingsTab === "privacy" && renderPrivacyPanel(currentPanel, diagnostics)}
        {settingsTab === "diagnostics" && renderDiagnosticsPanel(diagnostics)}
      </section>
    </div>
  );
}

function renderReadOnlyPanel(panel: SettingsPanel) {
  return (
    <div className="settings-grid">
      {panel.cards.map(([title, body]) => (
        <article className="setting-card" key={title}>
          <h3>{title}</h3>
          <p>{body}</p>
        </article>
      ))}
    </div>
  );
}

function renderLearningPanel(
  form: SettingsFormValue,
  onFieldChange: SettingsPageProps["onFieldChange"],
) {
  return (
    <div className="settings-form-grid">
      <label className="inline-field">
        <span>显示名称</span>
        <input
          value={form.displayName}
          placeholder="你的昵称"
          onChange={(event) => onFieldChange("displayName", event.target.value)}
        />
      </label>

      <label className="inline-field">
        <span>讲解风格</span>
        <select value={form.teachingPreference} onChange={(event) => onFieldChange("teachingPreference", event.target.value)}>
          <option value="step_by_step">逐步讲解</option>
          <option value="example_then_practice">先看示例再练习</option>
          <option value="minimal_guidance">最少引导</option>
        </select>
      </label>

      <label className="inline-field">
        <span>学习风格</span>
        <select value={form.learningStyle} onChange={(event) => onFieldChange("learningStyle", event.target.value)}>
          <option value="practice_first">先练后学</option>
          <option value="theory_first">先学后练</option>
          <option value="mixed">混合</option>
        </select>
      </label>

      <label className="inline-field">
        <span>反馈偏好</span>
        <select value={form.encouragementPreference} onChange={(event) => onFieldChange("encouragementPreference", event.target.value)}>
          <option value="direct">直接反馈</option>
          <option value="encouraging">鼓励式</option>
          <option value="socratic">苏格拉底式提问</option>
        </select>
      </label>

      <label className="inline-field">
        <span>职业背景</span>
        <input
          value={form.profession}
          placeholder="如：前端开发、学生、产品经理"
          onChange={(event) => onFieldChange("profession", event.target.value)}
        />
      </label>

      <label className="inline-field settings-span-2">
        <span>编程背景</span>
        <textarea
          value={form.backgroundContext}
          placeholder="简要描述你的编程经验，帮助 Agent 调整讲解粒度"
          onChange={(event) => onFieldChange("backgroundContext", event.target.value)}
        />
      </label>
    </div>
  );
}

function renderNotificationsPanel(
  form: SettingsFormValue,
  onFieldChange: SettingsPageProps["onFieldChange"],
) {
  return (
    <div className="settings-form-grid">
      <label className="settings-toggle settings-span-2">
        <span>启用学习提醒</span>
        <input
          checked={form.reminderEnabled}
          type="checkbox"
          onChange={(event) => onFieldChange("reminderEnabled", event.target.checked)}
        />
      </label>

      <label className="inline-field">
        <span>偏好学习日</span>
        <select value={form.preferredWeekday} onChange={(event) => onFieldChange("preferredWeekday", event.target.value)}>
          <option value="everyday">每天</option>
          <option value="weekday">工作日</option>
          <option value="weekend">周末</option>
        </select>
      </label>

      <label className="inline-field">
        <span>提醒渠道</span>
        <select value={form.reminderChannel} onChange={(event) => onFieldChange("reminderChannel", event.target.value)}>
          <option value="desktop">桌面通知</option>
          <option value="in_app">应用内提示</option>
        </select>
      </label>

      <label className="inline-field">
        <span>学习时段开始</span>
        <input type="time" value={form.preferredStart} onChange={(event) => onFieldChange("preferredStart", event.target.value)} />
      </label>

      <label className="inline-field">
        <span>学习时段结束</span>
        <input type="time" value={form.preferredEnd} onChange={(event) => onFieldChange("preferredEnd", event.target.value)} />
      </label>

      <label className="inline-field">
        <span>安静时段开始</span>
        <input type="time" value={form.quietHoursStart} onChange={(event) => onFieldChange("quietHoursStart", event.target.value)} />
      </label>

      <label className="inline-field">
        <span>安静时段结束</span>
        <input type="time" value={form.quietHoursEnd} onChange={(event) => onFieldChange("quietHoursEnd", event.target.value)} />
      </label>
    </div>
  );
}

function renderModelPanel(
  panel: SettingsPanel,
  diagnostics: SettingsPageProps["diagnostics"],
) {
  return (
    <>
      <div className="tool-card settings-callout">
        此处只显示当前服务状态。模型供应商和密钥在本地服务中配置，不在桌面端填写。
      </div>
      <div className="settings-grid">
        {panel.cards.map(([title, body]) => (
          <article className="setting-card" key={title}>
            <h3>{title}</h3>
            <p>{body}</p>
          </article>
        ))}
        <article className="setting-card">
          <h3>API Base URL</h3>
          <p>{diagnostics.apiBaseUrl}</p>
        </article>
        <article className="setting-card">
          <h3>服务诊断</h3>
          <p className={diagnostics.apiStatus === "在线" ? "status-ok" : "status-error"}>
            {diagnostics.apiStatus}
          </p>
        </article>
      </div>
    </>
  );
}

function renderReviewPanel(panel: SettingsPanel) {
  return (
    <>
      <div className="tool-card settings-callout">
        复习节奏由系统根据练习结果安排。这里先提供查看说明，暂不开放手动调节。
      </div>
      {renderReadOnlyPanel(panel)}
    </>
  );
}

function renderPrivacyPanel(
  panel: SettingsPanel,
  diagnostics: SettingsPageProps["diagnostics"],
) {
  return (
    <>
      <div className="tool-card settings-callout">
        当前用户{diagnostics.userId ? "已建立学习身份" : "尚未完成建档"}。这里仅展示恢复状态和本地记录边界，不提供一键清空、导出或删除。
      </div>
      <div className="settings-grid">
        {panel.cards.map(([title, body]) => (
          <article className="setting-card" key={title}>
            <h3>{title}</h3>
            <p>{body}</p>
          </article>
        ))}
        <article className="setting-card">
          <h3>当前计划</h3>
          <p>{diagnostics.planId ? "已绑定恢复上下文" : "尚未创建学习计划"}</p>
        </article>
        <article className="setting-card">
          <h3>恢复状态</h3>
          <p>{diagnostics.resumeAvailable ? "存在可恢复学习会话" : "当前没有待恢复会话"}</p>
        </article>
      </div>
    </>
  );
}

function renderDiagnosticsPanel(diagnostics: SettingsPageProps["diagnostics"]) {
  const apiOnline = diagnostics.apiStatus === "在线";

  return (
    <>
      <div className="tool-card settings-callout">
        这里显示桌面端能直接确认的连接、用户、计划和恢复状态。语言运行环境检测、安装指导和 runner 矩阵会在后续环境医生任务中接入。
      </div>
      <div className="settings-grid">
        <article className="setting-card">
          <h3>连接状态</h3>
          <p className={apiOnline ? "status-ok" : "status-error"}>{diagnostics.apiStatus}</p>
        </article>
        <article className="setting-card">
          <h3>用户</h3>
          <p>{diagnostics.userId ? "已登录" : "未登录"}</p>
        </article>
        <article className="setting-card">
          <h3>学习计划</h3>
          <p>{diagnostics.planId ? "已创建" : "未创建"}</p>
        </article>
        <article className="setting-card">
          <h3>API Base URL</h3>
          <p>{diagnostics.apiBaseUrl}</p>
        </article>
        <article className="setting-card">
          <h3>当前阶段</h3>
          <p>{diagnostics.currentStage ?? "暂无"}</p>
        </article>
        <article className="setting-card">
          <h3>今日待复习</h3>
          <p>{diagnostics.todayReviewCount} 项</p>
        </article>
        <article className="setting-card">
          <h3>恢复状态</h3>
          <p>{diagnostics.resumeAvailable ? "可恢复上次学习" : "当前没有待恢复会话"}</p>
        </article>
        <article className="setting-card">
          <h3>版本</h3>
          <p>Aearn Desktop V1</p>
        </article>
      </div>
    </>
  );
}

function saveStateLabel(value: SettingsPageProps["saveState"], isDirty: boolean) {
  if (value === "saving") {
    return "保存中";
  }
  if (value === "saved") {
    return "已保存";
  }
  if (value === "error") {
    return "保存失败";
  }
  return isDirty ? "未保存" : "";
}
