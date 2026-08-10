import { useEffect, useState, type FormEvent } from "react";

import { LearningHomePage } from "./features/learning/LearningHomePage";
import { LearningPlanBuilderPage } from "./features/learning/LearningPlanBuilderPage";
import { HarnessCutoverPage } from "./pages/HarnessCutoverPage";
import { useAppStore } from "./stores/useAppStore";
import type { LearningPlanSession } from "./types";

type TutorSurface =
  | { kind: "learning_home"; highlightedTrackId?: string }
  | { kind: "track_planner"; session: LearningPlanSession }
  | { kind: "downstream_not_ready"; intent: "continue_learning" | "start_review"; trackId: string };

function App() {
  const app = useAppStore();
  const [tutorSurface, setTutorSurface] = useState<TutorSurface>({ kind: "learning_home" });
  const [learningRefreshKey, setLearningRefreshKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void app.bootstrap(controller.signal);
    return () => controller.abort();
  }, [app.bootstrap]);

  useEffect(() => {
    setTutorSurface({ kind: "learning_home" });
  }, [app.activeRoute, app.user?.id]);

  if (!app.bootstrapHydrated || app.activeRoute === "loading") {
    return <LoadingScreen apiHealth={app.apiHealth} />;
  }

  if (app.activeRoute === "welcome") {
    return <WelcomeScreen actionState={app.dataActionState} actionMessage={app.dataActionMessage} onCreate={app.createLocalUser} />;
  }

  const routeLabel = app.activeRoute === "tutor"
    ? tutorSurface.kind === "learning_home"
      ? "学习主线"
      : tutorSurface.kind === "track_planner"
        ? "制定学习计划"
        : "学习入口"
    : "受控切换";
  const statusLabel =
    app.apiHealth.status === "online"
      ? "API 在线"
      : app.apiHealth.status === "offline"
        ? `API 离线：${app.apiHealth.message}`
        : "正在检查 API";
  const isSidebarlessTutorSurface = app.activeRoute === "tutor"
    && (tutorSurface.kind === "learning_home" || tutorSurface.kind === "track_planner");
  const desktopClassName = isSidebarlessTutorSurface
    ? "desktop learning-focus-shell"
    : app.sidebarOpen
      ? "desktop"
      : "desktop sidebar-collapsed";

  return (
    <main className="stage">
      <section className={desktopClassName} aria-label="Aearn Tutor">
        <header className="app-menu" aria-label="桌面应用菜单栏">
          <div className="menu-left">
            {!isSidebarlessTutorSurface && (
              <button
                className="sidebar-toggle"
                type="button"
                aria-label={app.sidebarOpen ? "折叠左侧栏" : "展开左侧栏"}
                aria-expanded={app.sidebarOpen}
                onClick={app.toggleSidebar}
              >
                <img src="/sidebar.png" alt="" />
              </button>
            )}
            <div className="app-title">Aearn Tutor</div>
          </div>
          <span className="harness-api-status" role="status">{statusLabel}</span>
        </header>

        {!isSidebarlessTutorSurface && (
          <aside className="sidebar tutor-sidebar" aria-label="Tutor 导航">
            <div className="brand">
              <span className="mark">A</span>
              <span className="brand-name">Aearn Tutor</span>
            </div>
            {app.activeRoute === "tutor" ? (
              <LearningPrimarySidebar onHome={() => setTutorSurface({ kind: "learning_home" })} />
            ) : (
              <section className="harness-shell-nav" aria-label="当前入口">
                <strong>{routeLabel}</strong>
                <span>服务器会先核对摘要，再执行任何清理。</span>
              </section>
            )}
          </aside>
        )}

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
            ) : app.user && tutorSurface.kind === "learning_home" ? (
              <LearningHomePage
                user={app.user}
                refreshKey={learningRefreshKey}
                highlightedTrackId={tutorSurface.highlightedTrackId}
                onOpenPlanner={(session) => setTutorSurface({ kind: "track_planner", session })}
                onDownstreamIntent={(intent, trackId) => setTutorSurface({ kind: "downstream_not_ready", intent, trackId })}
              />
            ) : app.user && tutorSurface.kind === "track_planner" ? (
              <LearningPlanBuilderPage
                user={app.user}
                initialSession={tutorSurface.session}
                onBack={() => { setLearningRefreshKey((value) => value + 1); setTutorSurface({ kind: "learning_home" }); }}
                onConfirmed={(trackId) => { setLearningRefreshKey((value) => value + 1); setTutorSurface({ kind: "learning_home", highlightedTrackId: trackId }); }}
              />
            ) : tutorSurface.kind === "downstream_not_ready" ? (
              <DownstreamNotReady
                intent={tutorSurface.intent}
                onBack={() => setTutorSurface({ kind: "learning_home" })}
              />
            ) : null}
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

function LearningPrimarySidebar({ onHome }: { onHome: () => void }) {
  return (
    <nav className="learning-primary-nav" aria-label="学习导航">
      <button type="button" onClick={onHome}><span>学习主线</span><small>首页与真实进度</small></button>
      <div><strong>当前边界</strong><p>Lesson、Review 和完整三栏工作区将在后续任务交付。</p></div>
    </nav>
  );
}

function DownstreamNotReady({ intent, onBack }: { intent: "continue_learning" | "start_review"; onBack: () => void }) {
  const review = intent === "start_review";
  return (
    <section className="downstream-not-ready" aria-labelledby="downstream-not-ready-title">
      <p className="tutor-panel-eyebrow">稳定导航意图已记录</p>
      <h1 id="downstream-not-ready-title">{review ? "复习工作区尚未交付" : "课程工作区尚未交付"}</h1>
      <p>{review ? "到期数量来自服务端，但 ReviewSession 将由后续任务实现。" : "LearningTrack 已可作为权威主线，但 LessonDocument 与三栏工作区将由后续任务实现。"}</p>
      <button className="tutor-primary-button" type="button" onClick={onBack}>返回学习主线</button>
    </section>
  );
}

export default App;
