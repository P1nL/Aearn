import type { SettingsKey } from "../appTypes";
import { SETTING_PANELS } from "../lib/appContent";

type SettingsPageProps = {
  settingsTab: SettingsKey;
  onSettingsTabChange: (value: SettingsKey) => void;
};

export function SettingsPage({ settingsTab, onSettingsTabChange }: SettingsPageProps) {
  const currentSettingsPanel = SETTING_PANELS[settingsTab];

  return (
    <div className="settings-screen">
      <div className="kicker">Settings</div>
      <p>横向列表包含外观、模型设置、通知设置、Attempt 记录配置、练习设置和关于。</p>

      <div className="settings-tabs" role="tablist" aria-label="设置分类">
        {Object.entries(SETTING_PANELS).map(([key, panel]) => (
          <button
            className={settingsTab === key ? "settings-tab active" : "settings-tab"}
            key={key}
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
            <button className="btn primary" type="button">
              保存设置
            </button>
          </div>
          <div className="settings-grid">
            {currentSettingsPanel.cards.map(([title, body]) => (
              <article className="setting-card" key={`${settingsTab}-${title}`}>
                <h3>{title}</h3>
                <p>{body}</p>
              </article>
            ))}
          </div>
        </section>

        <aside className="panel pad stack">
          <h2>当前配置摘要</h2>
          <div className="settings-mini active">
            <h3 className="mini-title">提示策略</h3>
            <p className="mini-body">先 hint 后解释，必要时再给最小代码片段。</p>
          </div>
          <div className="settings-mini">
            <h3 className="mini-title">提醒策略</h3>
            <p className="mini-body">due_at 到期时，优先进入复习页。</p>
          </div>
          <div className="settings-mini">
            <h3 className="mini-title">代码控制权</h3>
            <p className="mini-body">Agent 可解释错因，但用户保留最终补全权。</p>
          </div>
        </aside>
      </div>
    </div>
  );
}
