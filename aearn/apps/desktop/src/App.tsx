import { useEffect, useState, type FormEvent } from "react";

import { HarnessCutoverPage } from "./pages/HarnessCutoverPage";
import { TutorWorkspacePage } from "./pages/TutorWorkspacePage";
import { useAppStore } from "./stores/useAppStore";

function App() {
  const app = useAppStore();

  useEffect(() => {
    const controller = new AbortController();
    void app.bootstrap(controller.signal);
    return () => controller.abort();
  }, [app.bootstrap]);

  if (!app.bootstrapHydrated || app.activeRoute === "loading") {
    return <LoadingScreen apiHealth={app.apiHealth} />;
  }

  if (app.activeRoute === "welcome") {
    return <WelcomeScreen actionState={app.dataActionState} actionMessage={app.dataActionMessage} onCreate={app.createLocalUser} />;
  }

  const routeLabel = app.activeRoute === "tutor" ? "Tutor 工作区" : "受控切换";
  const statusLabel =
    app.apiHealth.status === "online"
      ? "API 在线"
      : app.apiHealth.status === "offline"
        ? `API 离线：${app.apiHealth.message}`
        : "正在检查 API";

  return (
    <main className="stage">
      <section className={app.sidebarOpen ? "desktop" : "desktop sidebar-collapsed"} aria-label="Aearn Tutor">
        <header className="app-menu" aria-label="桌面应用菜单栏">
          <div className="menu-left">
            <button
              className="sidebar-toggle"
              type="button"
              aria-label={app.sidebarOpen ? "折叠左侧栏" : "展开左侧栏"}
              aria-expanded={app.sidebarOpen}
              onClick={app.toggleSidebar}
            >
              <img src="/sidebar.png" alt="" />
            </button>
            <div className="app-title">Aearn Tutor</div>
          </div>
          <span className="harness-api-status" role="status">{statusLabel}</span>
        </header>

        <aside className="sidebar no-context" aria-label="Tutor 导航">
          <div className="brand">
            <span className="mark">A</span>
            <span className="brand-name">Aearn Tutor</span>
          </div>
          <section className="harness-shell-nav" aria-label="当前入口">
            <strong>{routeLabel}</strong>
            <span>
              {app.activeRoute === "tutor"
                ? "从当前目标开始。学习记录、计划与偏好由 Tutor 的安全边界管理。"
                : "服务器会先核对摘要，再执行任何清理。"}
            </span>
          </section>
        </aside>

        <section className="main" aria-label={routeLabel}>
          <header className="topbar">
            <div className="crumb">{routeLabel}</div>
            {app.user && <div className="tutor-user-label">{app.user.display_name}</div>}
          </header>
          <div className="workspace-shell harness-workspace-shell">
            {app.activeRoute === "cutover" ? (
              <HarnessCutoverPage
                user={app.user}
                decision={app.cutoverDecision}
                actionState={app.dataActionState}
                actionMessage={app.dataActionMessage}
                onConfirm={app.confirmHarnessCutover}
                onRefresh={app.refreshHarnessCutover}
              />
            ) : (
              <TutorWorkspacePage user={app.user} enabled isActive initialConversationId={null} />
            )}
          </div>
        </section>
      </section>
    </main>
  );
}

type LoadingScreenProps = {
  apiHealth: ReturnType<typeof useAppStore.getState>["apiHealth"];
};

function LoadingScreen({ apiHealth }: LoadingScreenProps) {
  const detail = apiHealth.status === "offline" ? apiHealth.message : "正在读取本地身份与服务器切换状态。";
  return (
    <main className="stage">
      <section className="harness-cutover-page" aria-live="polite">
        <div className="harness-cutover-card">
          <p className="harness-cutover-eyebrow">Aearn Tutor</p>
          <h1>正在准备学习工作区</h1>
          <p>{detail}</p>
        </div>
      </section>
    </main>
  );
}

type WelcomeScreenProps = {
  actionState: "idle" | "loading" | "success" | "error";
  actionMessage: string | null;
  onCreate: (displayName: string) => Promise<boolean>;
};

function WelcomeScreen({ actionState, actionMessage, onCreate }: WelcomeScreenProps) {
  const [displayName, setDisplayName] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onCreate(displayName);
  }

  return (
    <main className="stage">
      <section className="harness-cutover-page" aria-labelledby="tutor-welcome-title">
        <form className="harness-cutover-card" onSubmit={(event) => void handleSubmit(event)}>
          <p className="harness-cutover-eyebrow">Aearn Tutor</p>
          <h1 id="tutor-welcome-title">从你的学习目标开始</h1>
          <p>先创建一个保存在本机的身份。进入 Tutor 后，你可以直接说明想学什么、正在解决什么问题，或粘贴需要一起分析的代码。</p>
          <label className="harness-cutover-confirm-checkbox" htmlFor="tutor-display-name">
            <span>显示名称</span>
            <input
              id="tutor-display-name"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              placeholder="例如：小林"
              autoComplete="name"
              disabled={actionState === "loading"}
            />
          </label>
          <div className="harness-cutover-actions">
            <button className="harness-cutover-primary" type="submit" disabled={!displayName.trim() || actionState === "loading"}>
              {actionState === "loading" ? "正在创建……" : "进入 Tutor"}
            </button>
          </div>
          {actionMessage && (
            <p className={actionState === "error" ? "harness-cutover-feedback error" : "harness-cutover-feedback"} role={actionState === "error" ? "alert" : "status"}>
              {actionMessage}
            </p>
          )}
        </form>
      </section>
    </main>
  );
}

export default App;
