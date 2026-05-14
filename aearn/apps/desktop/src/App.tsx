import { startTransition, useEffect, useState, type FormEvent } from "react";

import { fetchApiHealth, fetchLanguageCourses, startLearningSession } from "./api";
import type {
  ApiHealthState,
  AppRoute,
  ConversationMessage,
  NavGroupKey,
  SessionState,
  SettingsKey,
} from "./appTypes";
import { ApiHealthChip } from "./components/ApiHealthChip";
import { SidebarNav } from "./components/SidebarNav";
import { SideContext } from "./components/SideContext";
import {
  DEFAULT_ATTEMPT_NOTE,
  DEFAULT_NOTE_CONTENT,
  HOME_BASE_MESSAGES,
  NAV_DEFAULTS,
  ONBOARDING_MESSAGES,
  REVIEW_BASE_MESSAGES,
  ROUTE_META,
} from "./lib/appContent";
import { getCrumbLabel, screenClassName } from "./lib/desktopLabels";
import {
  applyKnowledgePointUpdate,
  buildAttemptDraft,
  buildSessionNote,
  computeSidebarProgress,
  createMessage,
  markKnowledgePointLearning,
  mergeAttemptIntoNote,
} from "./lib/learningHelpers";
import { LearningWorkspacePage } from "./pages/LearningWorkspacePage";
import { NotesPage } from "./pages/NotesPage";
import { OnboardingPage } from "./pages/OnboardingPage";
import { ReviewPage } from "./pages/ReviewPage";
import { SettingsPage } from "./pages/SettingsPage";
import type {
  CreatedPlanResponse,
  LanguageCourse,
  RunExerciseResponse,
  SubmitExerciseResponse,
  UserProfile,
} from "./types";

function App() {
  const [apiHealth, setApiHealth] = useState<ApiHealthState>({ status: "loading" });
  const [courses, setCourses] = useState<LanguageCourse[]>([]);
  const [user, setUser] = useState<UserProfile | null>(null);
  const [createdPlan, setCreatedPlan] = useState<CreatedPlanResponse | null>(null);
  const [sessionState, setSessionState] = useState<SessionState>({ status: "idle" });
  const [lastRun, setLastRun] = useState<RunExerciseResponse | null>(null);
  const [lastSubmit, setLastSubmit] = useState<SubmitExerciseResponse | null>(null);
  const [activeRoute, setActiveRoute] = useState<AppRoute>("onboarding");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [openGroups, setOpenGroups] = useState<Record<NavGroupKey, boolean>>(NAV_DEFAULTS);
  const [noteDrawerOpen, setNoteDrawerOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState<SettingsKey>("appearance");
  const [noteContent, setNoteContent] = useState(DEFAULT_NOTE_CONTENT);
  const [noteDrawerText, setNoteDrawerText] = useState(DEFAULT_ATTEMPT_NOTE);
  const [noteSaveState, setNoteSaveState] = useState("已保存");
  const [composerInput, setComposerInput] = useState("");
  const [homeConversation, setHomeConversation] = useState<ConversationMessage[]>([]);
  const [reviewConversation, setReviewConversation] = useState<ConversationMessage[]>([]);
  const [resetNonce, setResetNonce] = useState(0);

  const session = sessionState.status === "ready" ? sessionState.data : null;
  const activeExercise = session?.exercise ?? null;
  const activeKnowledgePointId =
    sessionState.status === "ready"
      ? sessionState.data.context_snapshot.KnowledgePoint.id
      : sessionState.status === "loading"
        ? sessionState.knowledgePointId
        : sessionState.status === "error"
          ? (sessionState.knowledgePointId ?? "")
          : "";
  const visibleRoute = activeRoute;
  const sidebarHint = ROUTE_META[visibleRoute].hint;
  const sidebarProgress = createdPlan ? computeSidebarProgress(createdPlan) : 0;
  const crumb = getCrumbLabel(visibleRoute, settingsTab, session, activeExercise);
  const homeMessages = [...HOME_BASE_MESSAGES, ...homeConversation];
  const reviewMessages = [...REVIEW_BASE_MESSAGES, ...reviewConversation];

  async function bootstrap(signal?: AbortSignal) {
    setApiHealth({ status: "loading" });

    try {
      const [health, catalog] = await Promise.all([fetchApiHealth(signal), fetchLanguageCourses(signal)]);
      startTransition(() => {
        setApiHealth({ status: "online", data: health });
        setCourses(catalog);
      });
    } catch (error) {
      if (signal?.aborted) {
        return;
      }
      setApiHealth({
        status: "offline",
        message: error instanceof Error ? error.message : "Unable to reach API service",
      });
    }
  }

  async function openLearningSession(planResponse: CreatedPlanResponse, knowledgePointId: string, activeUserId?: string) {
    const userId = activeUserId ?? user?.id;
    if (!userId) {
      setSessionState({
        status: "error",
        knowledgePointId,
        message: "请先完成用户建档",
      });
      return;
    }

    setSessionState({ status: "loading", knowledgePointId });
    setLastRun(null);
    setLastSubmit(null);
    try {
      const response = await startLearningSession({
        userId,
        planId: planResponse.LearningPlan.id,
        knowledgePointId,
      });
      startTransition(() => {
        setSessionState({ status: "ready", data: response });
        setCreatedPlan((current) => markKnowledgePointLearning(current ?? planResponse, knowledgePointId));
        setActiveRoute("home");
      });
    } catch (error) {
      setSessionState({
        status: "error",
        knowledgePointId,
        message: error instanceof Error ? error.message : "无法启动学习会话",
      });
      setActiveRoute("home");
    }
  }

  async function handlePlanCreated(plan: CreatedPlanResponse, activeUser: UserProfile) {
    startTransition(() => {
      setUser(activeUser);
      setCreatedPlan(plan);
      setSessionState({ status: "idle" });
      setLastRun(null);
      setLastSubmit(null);
    });
    const nextKnowledgePointId = plan.next_entry_point.knowledge_point_id;
    if (nextKnowledgePointId) {
      await openLearningSession(plan, nextKnowledgePointId, activeUser.id);
      return;
    }
    setActiveRoute("home");
  }

  function handleKnowledgePointUpdate(patch: SubmitExerciseResponse["KnowledgePoint"]) {
    setCreatedPlan((current) => (current ? applyKnowledgePointUpdate(current, patch) : current));
    setSessionState((current) =>
      current.status === "ready"
        ? {
            status: "ready",
            data: {
              ...current.data,
              context_snapshot: {
                ...current.data.context_snapshot,
                KnowledgePoint: {
                  ...current.data.context_snapshot.KnowledgePoint,
                  status: patch.status,
                },
              },
            },
          }
        : current,
    );
  }

  function goToRoute(route: AppRoute) {
    setActiveRoute(route);
    closeDrawers();
  }

  function closeDrawers() {
    setNoteDrawerOpen(false);
  }

  function toggleSidebar() {
    setSidebarOpen((current) => !current);
  }

  function toggleGroup(group: NavGroupKey) {
    setOpenGroups((current) => ({ ...current, [group]: !current[group] }));
  }

  function resetGoal() {
    setCreatedPlan(null);
    setSessionState({ status: "idle" });
    setLastRun(null);
    setLastSubmit(null);
    setHomeConversation([]);
    setReviewConversation([]);
    setComposerInput("");
    setSettingsTab("appearance");
    setNoteContent(DEFAULT_NOTE_CONTENT);
    setNoteDrawerText(DEFAULT_ATTEMPT_NOTE);
    setNoteSaveState("已保存");
    setActiveRoute("onboarding");
    setResetNonce((current) => current + 1);
    closeDrawers();
  }

  function handleComposerSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (composerInput.trim().length === 0) {
      return;
    }
    if (visibleRoute === "review") {
      setReviewConversation((current) => [
        ...current,
        createMessage("user", composerInput.trim()),
        createMessage("agent", "收到。先按准确性、因果链、例子质量和表达清晰度评分，再决定下一次 due_at。", "Agent"),
      ]);
    } else {
      setHomeConversation((current) => [
        ...current,
        createMessage("user", composerInput.trim()),
        createMessage("agent", "收到。先把失败用例和你刚修改的那一行对齐，再决定是重跑、提交，还是继续追问错因。", "Agent"),
      ]);
    }
    setComposerInput("");
  }

  function handleSaveAttempt() {
    setNoteContent((current) => mergeAttemptIntoNote(current, noteDrawerText));
    setNoteSaveState("已保存");
  }

  function handleOpenNoteDrawer() {
    setNoteDrawerOpen(true);
  }

  useEffect(() => {
    const controller = new AbortController();
    void bootstrap(controller.signal);

    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (session && activeExercise) {
      setNoteContent(buildSessionNote(session, activeExercise));
      setNoteDrawerText(buildAttemptDraft(activeExercise, lastRun, lastSubmit));
      setNoteSaveState("已保存");
    }
  }, [session?.session_id, activeExercise?.id]);

  useEffect(() => {
    if (activeExercise) {
      setNoteDrawerText(buildAttemptDraft(activeExercise, lastRun, lastSubmit));
      setNoteSaveState("已保存");
    }
  }, [activeExercise?.id, lastRun?.attempt_id, lastSubmit?.attempt_id]);

  useEffect(() => {
    if (createdPlan && activeRoute === "onboarding") {
      setActiveRoute("home");
    }
  }, [createdPlan, activeRoute]);

  return (
    <main className="stage">
      <section className={sidebarOpen ? "desktop" : "desktop sidebar-collapsed"} aria-label="Claude 桌面端风格 Aearn 框架">
        <header className="app-menu" aria-label="桌面应用菜单栏">
          <div className="menu-left">
            {sidebarOpen ? (
              <button className="sidebar-toggle" type="button" aria-label="折叠左侧栏" aria-expanded="true" onClick={toggleSidebar}>
                <img src="/sidebar.png" alt="" />
              </button>
            ) : (
              <button className="sidebar-toggle" type="button" aria-label="展开左侧栏" aria-expanded="false" onClick={toggleSidebar}>
                <img src="/sidebar.png" alt="" />
              </button>
            )}
            <div className="app-title">AI Code Learning</div>
          </div>
          <div className="menu-right">
            <button className="menu-icon settings-top" type="button" aria-label="设置" onClick={() => goToRoute("settings")}>
              <svg width="15" height="15" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M12 15.4a3.4 3.4 0 1 0 0-6.8 3.4 3.4 0 0 0 0 6.8Z"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                />
                <path
                  d="M19.3 13.5c.1-.5.1-1 .1-1.5s0-1-.1-1.5l2-1.5-2-3.5-2.4 1a7 7 0 0 0-2.6-1.5L14 2.4h-4L9.7 5a7 7 0 0 0-2.6 1.5l-2.4-1-2 3.5 2 1.5a8.6 8.6 0 0 0 0 3l-2 1.5 2 3.5 2.4-1a7 7 0 0 0 2.6 1.5l.3 2.6h4l.3-2.6a7 7 0 0 0 2.6-1.5l2.4 1 2-3.5-2-1.5Z"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
            <div className="window-controls" aria-hidden="true">
              <span className="window-btn">−</span>
              <span className="window-btn">□</span>
              <span className="window-btn">×</span>
            </div>
          </div>
        </header>

        <aside className={visibleRoute === "settings" ? "sidebar no-context" : "sidebar"} aria-label="应用侧边栏">
          <div className="brand">
            <span className="mark">A</span>
            <span className="brand-name">AI Code Learning</span>
          </div>

          <button className="new-goal" type="button" onClick={resetGoal}>
            <span>新编程目标</span>
            <span>+</span>
          </button>

          <SidebarNav
            activeRoute={visibleRoute}
            createdPlan={createdPlan}
            activeKnowledgePointId={activeKnowledgePointId}
            openGroups={openGroups}
            onToggleGroup={toggleGroup}
            onRouteChange={goToRoute}
          />

          <SideContext
            route={visibleRoute}
            createdPlan={createdPlan}
            activeKnowledgePointId={activeKnowledgePointId}
            lastSubmit={lastSubmit}
            onSelectKnowledgePoint={(knowledgePointId) => {
              if (createdPlan) {
                void openLearningSession(createdPlan, knowledgePointId);
              }
            }}
          />

          <footer className="sidebar-footer">
            <progress className="progress" aria-label={`总进度 ${Math.round(sidebarProgress * 100)}%`} max={100} value={Math.round(sidebarProgress * 100)} />
            <span>{sidebarHint}</span>
          </footer>
        </aside>

        <section className="main" aria-label="工作区">
          <header className="topbar">
            <div className="crumb">{crumb}</div>
            <ApiHealthChip apiHealth={apiHealth} />
          </header>

          <section className={screenClassName(visibleRoute === "onboarding")} aria-label="首次建档">
            <OnboardingPage
              apiHealth={apiHealth}
              courses={courses}
              existingUser={user}
              messages={ONBOARDING_MESSAGES}
              resetNonce={resetNonce}
              onUserChange={setUser}
              onPlanCreated={handlePlanCreated}
            />
          </section>

          <section className={screenClassName(visibleRoute === "home")} aria-label="学习页">
            <LearningWorkspacePage
              createdPlan={createdPlan}
              sessionState={sessionState}
              messages={homeMessages}
              lastRun={lastRun}
              lastSubmit={lastSubmit}
              resetNonce={resetNonce}
              onOpenLearningSession={openLearningSession}
              onRunChange={setLastRun}
              onSubmitChange={setLastSubmit}
              onKnowledgePointUpdate={handleKnowledgePointUpdate}
              onOpenNoteDrawer={handleOpenNoteDrawer}
            />
          </section>

          <section className={screenClassName(visibleRoute === "review")} aria-label="复习页">
            <ReviewPage
              isActive={visibleRoute === "review"}
              user={user}
              messages={reviewMessages}
              lastSubmit={lastSubmit}
              lastRun={lastRun}
            />
          </section>

          <section className={screenClassName(visibleRoute === "notes")} aria-label="笔记页">
            <NotesPage noteContent={noteContent} onNoteContentChange={setNoteContent} />
          </section>

          <section className={screenClassName(visibleRoute === "settings")} aria-label="设置页">
            <SettingsPage settingsTab={settingsTab} onSettingsTabChange={setSettingsTab} />
          </section>

          <div className={noteDrawerOpen ? "drawer-scrim open" : "drawer-scrim"} onClick={closeDrawers}></div>

          {noteDrawerOpen ? (
            <section id="noteDrawer" className="drawer open" aria-label="尝试记录弹窗" aria-hidden="false">
              <div className="drawer-head">
                <h2>尝试记录</h2>
                <div className="note-status">
                  <span>{noteSaveState}</span>
                  <button className="icon-btn" type="button" aria-label="保存尝试记录" onClick={handleSaveAttempt}>
                    ✓
                  </button>
                </div>
              </div>
              <textarea
                className="drawer-editor"
                aria-label="尝试记录编辑器"
                value={noteDrawerText}
                onChange={(event) => {
                  setNoteDrawerText(event.target.value);
                  setNoteSaveState("未保存");
                }}
              />
            </section>
          ) : (
            <section id="noteDrawer" className="drawer" aria-label="尝试记录弹窗" aria-hidden="true">
              <div className="drawer-head">
                <h2>尝试记录</h2>
                <div className="note-status">
                  <span>{noteSaveState}</span>
                  <button className="icon-btn" type="button" aria-label="保存尝试记录" onClick={handleSaveAttempt}>
                    ✓
                  </button>
                </div>
              </div>
              <textarea
                className="drawer-editor"
                aria-label="尝试记录编辑器"
                value={noteDrawerText}
                onChange={(event) => {
                  setNoteDrawerText(event.target.value);
                  setNoteSaveState("未保存");
                }}
              />
            </section>
          )}

          {(visibleRoute === "home" || visibleRoute === "review") && (
            <form className="composer-wrap" onSubmit={handleComposerSubmit}>
              <div className="composer">
                <textarea
                  aria-label="代码练习输入框"
                  value={composerInput}
                  placeholder={visibleRoute === "review" ? "用自己的话复述，或请求提示……" : "粘贴你的代码、运行输出、测试失败或请 Agent 解释错因……"}
                  onChange={(event) => setComposerInput(event.target.value)}
                />
                {noteDrawerOpen ? (
                  <button
                    className="btn primary send-btn note-inline-btn"
                    type="button"
                    aria-label="关闭尝试记录"
                    aria-controls="noteDrawer"
                    aria-expanded="true"
                    onClick={() => {
                      setNoteDrawerOpen(false);
                    }}
                  >
                    <img src="/note.png" alt="" />
                  </button>
                ) : (
                  <button
                    className="btn primary send-btn note-inline-btn"
                    type="button"
                    aria-label="打开尝试记录"
                    aria-controls="noteDrawer"
                    aria-expanded="false"
                    onClick={() => {
                      setNoteDrawerOpen(true);
                    }}
                  >
                    <img src="/note.png" alt="" />
                  </button>
                )}
                <button className="btn primary send-btn" type="submit" aria-label="发送">
                  ↑
                </button>
              </div>
            </form>
          )}
        </section>
      </section>
    </main>
  );
}

export default App;
