import { useCallback, useEffect, useState } from "react";

import { API_BASE_URL, fetchEnvironmentDoctor } from "./api";
import type { AppRoute, EnvironmentDoctorState, NoteContext } from "./appTypes";
import { ApiHealthChip } from "./components/ApiHealthChip";
import { NoteDrawer } from "./components/NoteDrawer";
import { SidebarNav } from "./components/SidebarNav";
import { SideContext } from "./components/SideContext";
import { ROUTE_META } from "./lib/appContent";
import { writeBootstrapContext, clearBootstrapContext } from "./lib/bootstrapStorage";
import { getCrumbLabel, screenClassName } from "./lib/desktopLabels";
import { computeSidebarProgress } from "./lib/learningHelpers";
import { useAutoSave } from "./hooks/useAutoSave";
import { useAppStore } from "./stores/useAppStore";
import { useNotesStore } from "./stores/useNotesStore";
import { useSettingsStore } from "./stores/useSettingsStore";
import { LearningWorkspacePage } from "./pages/LearningWorkspacePage";
import { NotesPage } from "./pages/NotesPage";
import { OnboardingPage } from "./pages/OnboardingPage";
import { ReviewPage } from "./pages/ReviewPage";
import { SettingsPage } from "./pages/SettingsPage";
import type { LearningSessionResponse, LocalUserListItem } from "./types";

function App() {
  const app = useAppStore();
  const notes = useNotesStore();
  const settings = useSettingsStore();
  const [environmentDoctor, setEnvironmentDoctor] = useState<EnvironmentDoctorState>({ status: "idle" });
  const [selectedReviewKnowledgePointId, setSelectedReviewKnowledgePointId] = useState<string | null>(null);

  const dashboard = app.dashboardState.status === "ready" ? app.dashboardState.data : null;
  const session = app.sessionState.status === "ready" ? app.sessionState.data : null;
  const activeExercise = session?.exercise ?? null;
  const currentPlanId = app.createdPlan?.LearningPlan.id ?? null;
  const activeKnowledgePointId =
    app.sessionState.status === "ready"
      ? app.sessionState.data.context_snapshot.KnowledgePoint.id
      : app.sessionState.status === "loading"
        ? app.sessionState.knowledgePointId
        : app.sessionState.status === "error"
          ? (app.sessionState.knowledgePointId ?? "")
          : "";

  const visibleRoute = app.activeRoute;
  const sidebarActiveKnowledgePointId = visibleRoute === "review" ? (selectedReviewKnowledgePointId ?? "") : activeKnowledgePointId;
  const sidebarHint = ROUTE_META[visibleRoute].hint;
  const sidebarProgress = app.createdPlan ? computeSidebarProgress(app.createdPlan) : 0;
  const crumb = getCrumbLabel(visibleRoute, settings.settingsTab, session, activeExercise);
  const homeMessages = app.homeConversation;
  const reviewMessages = app.reviewConversation;
  const settingsDirty = settings.isDirty(app.user);
  const apiStatusLabel =
    app.apiHealth.status === "online" ? "在线" : app.apiHealth.status === "offline" ? `离线: ${app.apiHealth.message}` : "检测中";

  const currentSessionNoteContext = buildLearningNoteContext(session);
  const currentContext = currentSessionNoteContext ?? notes.reviewNoteContext;
  const drawerKnowledgePointId = notes.drawerContext?.knowledgePointId ?? null;
  const drawerNote = drawerKnowledgePointId ? notes.notesByKnowledgePointId[drawerKnowledgePointId] ?? null : null;
  const drawerDraft = drawerKnowledgePointId ? notes.noteDrafts[drawerKnowledgePointId] ?? null : null;
  const selectedDraft = notes.pageSelection ? notes.noteDrafts[notes.pageSelection] ?? null : null;
  const activeEditorKnowledgePointId = notes.drawerOpen ? drawerKnowledgePointId : visibleRoute === "notes" ? notes.pageSelection : null;
  const canOpenNoteDrawer = Boolean(app.user && ((visibleRoute === "home" && currentSessionNoteContext) || (visibleRoute === "review" && notes.reviewNoteContext)));
  const lastAttemptId = app.lastSubmit?.attempt_id ?? app.lastRun?.attempt_id;

  // --- Auto-save ---
  const autoSaveValue = activeEditorKnowledgePointId ? (notes.noteDrafts[activeEditorKnowledgePointId]?.content ?? "") : "";
  const autoSaveEnabled = Boolean(activeEditorKnowledgePointId && notes.noteDrafts[activeEditorKnowledgePointId]?.status === "未保存");
  const handleAutoSave = useCallback(
    async (_value: string) => {
      if (!activeEditorKnowledgePointId) return false;
      return notes.saveByKnowledgePointId(activeEditorKnowledgePointId);
    },
    [activeEditorKnowledgePointId],
  );
  const { flush: flushAutoSave } = useAutoSave(autoSaveValue, handleAutoSave, { delay: 800, enabled: autoSaveEnabled });

  // --- Handlers ---
  async function goToRoute(route: AppRoute) {
    const closed = await closeDrawers();
    if (!closed) return;
    if (route === "review") {
      setSelectedReviewKnowledgePointId(null);
    }
    app.setActiveRoute(route);
  }

  async function closeDrawers() {
    if (!notes.drawerOpen || !drawerKnowledgePointId) {
      notes.setDrawerOpen(false);
      return true;
    }
    const draft = notes.noteDrafts[drawerKnowledgePointId];
    if (draft?.status === "未保存") {
      const saved = await flushAutoSave();
      if (!saved) return false;
    }
    notes.setDrawerOpen(false);
    return true;
  }

  async function handleSaveSettings() {
    if (!app.user) return;
    const updated = await settings.save(app.user.id);
    if (updated) app.setUser(updated);
  }

  async function handleOpenNoteDrawer() {
    const context = visibleRoute === "review" ? notes.reviewNoteContext : currentSessionNoteContext;
    if (!context || !app.user) return;
    notes.setDrawerContext(context);
    notes.setDrawerOpen(true);
    const note = await notes.ensureForContext(app.user.id, context);
    if (note) notes.setPageSelection(notes.pageSelection ?? note.knowledge_point_id);
  }

  async function handleSelectReviewKnowledgePoint(knowledgePointId: string) {
    const closed = await closeDrawers();
    if (!closed) return;
    setSelectedReviewKnowledgePointId(knowledgePointId);
    app.setActiveRoute("review");
  }

  function handleResetGoal() {
    app.resetGoal();
    settings.setTab("learning");
    notes.reset();
  }

  async function handleSwitchLocalUser(item: LocalUserListItem) {
    const closed = await closeDrawers();
    if (!closed) return;
    notes.reset();
    await app.switchLocalUser(item);
  }

  async function handleExportUserData() {
    await app.exportActiveUserData();
  }

  async function handleResetUserData() {
    const closed = await closeDrawers();
    if (!closed) return;
    const ok = await app.resetActiveUserData();
    if (ok) {
      notes.reset();
      settings.setTab("learning");
    }
  }

  async function handleDeleteUserData() {
    const closed = await closeDrawers();
    if (!closed) return;
    const ok = await app.deleteActiveUser();
    if (ok) {
      notes.reset();
      settings.setTab("privacy");
    }
  }

  const refreshEnvironmentDoctor = useCallback(async (signal?: AbortSignal) => {
    setEnvironmentDoctor({ status: "loading" });
    try {
      const data = await fetchEnvironmentDoctor(signal);
      if (signal?.aborted) return;
      setEnvironmentDoctor({ status: "ready", data });
    } catch (error) {
      if (signal?.aborted) return;
      setEnvironmentDoctor({
        status: "error",
        message: error instanceof Error ? error.message : "环境检测失败",
      });
    }
  }, []);

  // --- Effects ---
  useEffect(() => {
    if (app.user) settings.syncFromUser(app.user);
  }, [app.user?.id, app.user?.updated_at]);

  useEffect(() => {
    setSelectedReviewKnowledgePointId(null);
  }, [app.user?.id, app.createdPlan?.LearningPlan.id]);

  useEffect(() => {
    if (!app.bootstrapHydrated) return;
    if (!app.user?.id) { clearBootstrapContext(); return; }
    writeBootstrapContext({ userId: app.user.id, planId: app.createdPlan?.LearningPlan.id ?? null });
  }, [app.bootstrapHydrated, app.user?.id, app.createdPlan?.LearningPlan.id]);

  useEffect(() => {
    const controller = new AbortController();
    void app.bootstrap(controller.signal);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (visibleRoute !== "notes" || !app.user) return;
    const controller = new AbortController();
    void notes.loadIndex(app.user.id, controller.signal);
    return () => controller.abort();
  }, [visibleRoute, app.user?.id]);

  useEffect(() => {
    if (notes.notesList.length === 0) return;
    if (notes.pageSelection && notes.notesByKnowledgePointId[notes.pageSelection]) return;
    notes.setPageSelection(notes.notesList[0]?.knowledge_point_id ?? null);
  }, [notes.notesList, notes.notesByKnowledgePointId]);

  useEffect(() => {
    if (visibleRoute !== "settings" || settings.settingsTab !== "diagnostics" || environmentDoctor.status !== "idle") {
      return;
    }
    void refreshEnvironmentDoctor();
  }, [visibleRoute, settings.settingsTab, environmentDoctor.status, refreshEnvironmentDoctor]);

  useEffect(() => {
    if (visibleRoute !== "settings" || settings.settingsTab !== "privacy") {
      return;
    }
    const controller = new AbortController();
    void app.loadLocalUsers(controller.signal);
    void app.loadUserDataSummary(undefined, controller.signal);
    return () => controller.abort();
  }, [visibleRoute, settings.settingsTab, app.user?.id]);

  useEffect(() => {
    if (!notes.drawerOpen || !notes.drawerContext) return;
    if (!notes.notesByKnowledgePointId[notes.drawerContext.knowledgePointId] && app.user) {
      void notes.ensureForContext(app.user.id, notes.drawerContext);
    }
  }, [notes.drawerOpen, notes.drawerContext?.knowledgePointId]);

  // --- Render ---
  return (
    <main className="stage">
      <section className={app.sidebarOpen ? "desktop" : "desktop sidebar-collapsed"} aria-label="Aearn 对话学习工作台">
        <header className="app-menu" aria-label="桌面应用菜单栏">
          <div className="menu-left">
            <button className="sidebar-toggle" type="button" aria-label={app.sidebarOpen ? "折叠左侧栏" : "展开左侧栏"} aria-expanded={app.sidebarOpen} onClick={app.toggleSidebar}>
              <img src="/sidebar.png" alt="" />
            </button>
            <div className="app-title">Aearn Dialogue</div>
          </div>
          <div className="menu-right">
            <button className="menu-icon settings-top" type="button" aria-label="设置" onClick={() => goToRoute("settings")}>
              <svg width="15" height="15" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 15.4a3.4 3.4 0 1 0 0-6.8 3.4 3.4 0 0 0 0 6.8Z" fill="none" stroke="currentColor" strokeWidth="2" />
                <path d="M19.3 13.5c.1-.5.1-1 .1-1.5s0-1-.1-1.5l2-1.5-2-3.5-2.4 1a7 7 0 0 0-2.6-1.5L14 2.4h-4L9.7 5a7 7 0 0 0-2.6 1.5l-2.4-1-2 3.5 2 1.5a8.6 8.6 0 0 0 0 3l-2 1.5 2 3.5 2.4-1a7 7 0 0 0 2.6 1.5l.3 2.6h4l.3-2.6a7 7 0 0 0 2.6-1.5l2.4 1 2-3.5-2-1.5Z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
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
            <span className="brand-name">Aearn Dialogue</span>
          </div>
          <button className="new-goal" type="button" onClick={handleResetGoal}>
            <span>新学习目标</span><span>+</span>
          </button>
          <SidebarNav
            activeRoute={visibleRoute}
            createdPlan={app.createdPlan}
            activeKnowledgePointId={sidebarActiveKnowledgePointId}
            openGroups={app.openGroups}
            onToggleGroup={app.toggleGroup}
            onRouteChange={goToRoute}
            onSelectKnowledgePoint={(id) => {
              if (app.createdPlan) {
                void app.openLearningSession(app.createdPlan, id);
              }
            }}
            onSelectReviewKnowledgePoint={(id) => void handleSelectReviewKnowledgePoint(id)}
          />
          <SideContext
            route={visibleRoute}
            createdPlan={app.createdPlan}
            activeKnowledgePointId={activeKnowledgePointId}
            onSelectKnowledgePoint={(id) => { if (app.createdPlan) void app.openLearningSession(app.createdPlan, id); }}
          />
          <footer className="sidebar-footer">
            <progress className="progress" aria-label={`总进度 ${Math.round(sidebarProgress * 100)}%`} max={100} value={Math.round(sidebarProgress * 100)} />
            <span>{sidebarHint}</span>
          </footer>
        </aside>

        <section className="main" aria-label="工作区">
          <header className="topbar">
            <div className="crumb">{crumb}</div>
            <ApiHealthChip apiHealth={app.apiHealth} />
          </header>

          <div className="workspace-shell">
            {dashboard && visibleRoute !== "onboarding" && visibleRoute !== "home" && visibleRoute !== "review" && (
              <section className={dashboard.next_entry_point.type === "review" ? "dashboard-banner warning" : "dashboard-banner"} aria-label="恢复与复习提示">
                <div className="dashboard-banner-copy">
                  <strong>{dashboard.current_stage ?? "当前学习"}</strong>
                  <span>今日复习 {dashboard.today_review_count} · 总进度 {Math.round(dashboard.overall_progress * 100)}%</span>
                  <span>
                    {dashboard.next_entry_point.type === "review"
                      ? "你有一段时间没学习了，建议先复习巩固。"
                      : dashboard.resume_available ? "可以继续上次的学习进度。" : "准备好了就开始学习吧。"}
                  </span>
                </div>
                <div className="dashboard-banner-actions">
                  {dashboard.today_review_count > 0 && <button className="btn ghost" type="button" onClick={() => void goToRoute("review")}>今日复习</button>}
                  {dashboard.resume_available && <button className="btn ghost" type="button" onClick={() => void app.handleResumeShortcut()}>恢复上次</button>}
                  {app.createdPlan && <button className="btn primary" type="button" onClick={() => void app.handleStartCurrentLearning()}>当前学习</button>}
                </div>
              </section>
            )}

            {app.dashboardState.status === "error" && <div className="tool-card dashboard-inline-error">提示：{app.dashboardState.message}</div>}

            <section className={screenClassName(visibleRoute === "onboarding")} aria-label="首次建档">
              <OnboardingPage apiHealth={app.apiHealth} existingUser={app.user} resetNonce={app.resetNonce} onUserChange={app.setUser} onPlanCreated={app.handlePlanCreated} />
            </section>

            <section className={screenClassName(visibleRoute === "home")} aria-label="学习页">
              <LearningWorkspacePage
                user={app.user}
                createdPlan={app.createdPlan}
                sessionState={app.sessionState}
                messages={homeMessages}
                lastRun={app.lastRun}
                lastSubmit={app.lastSubmit}
                resetNonce={app.resetNonce}
                canOpenNoteDrawer={canOpenNoteDrawer}
                noteDrawerOpen={notes.drawerOpen}
                onOpenLearningSession={app.openLearningSession}
                onReturnToRoute={app.clearLearningSession}
                onRunChange={app.setLastRun}
                onSubmitChange={app.setLastSubmit}
                onKnowledgePointUpdate={app.handleKnowledgePointUpdate}
                onOpenNoteDrawer={() => void handleOpenNoteDrawer()}
                onCloseNoteDrawer={() => void closeDrawers()}
                onAddMessage={app.addHomeMessage}
                onUpdateMessage={app.updateHomeMessage}
                onStartToolCall={app.startHomeToolCall}
                onAppendToolCallDelta={app.appendHomeToolCallDelta}
                onFinalizeToolCall={app.finalizeHomeToolCall}
              />
            </section>

            <section className={screenClassName(visibleRoute === "review")} aria-label="复习页">
              <ReviewPage
                isActive={visibleRoute === "review"}
                user={app.user}
                selectedKnowledgePointId={selectedReviewKnowledgePointId}
                messages={reviewMessages}
                onActiveKnowledgePointChange={setSelectedReviewKnowledgePointId}
                onActiveNoteContextChange={notes.setReviewNoteContext}
              />
            </section>

            <section className={screenClassName(visibleRoute === "notes")} aria-label="笔记页">
              <NotesPage
                loadState={notes.loadState}
                errorMessage={notes.errorMessage}
                notes={notes.notesList}
                selectedKnowledgePointId={notes.pageSelection}
                currentContext={currentContext}
                selectedDraft={selectedDraft}
                assistLoading={Boolean(notes.pageSelection && notes.assistBusy[notes.pageSelection])}
                onSelectKnowledgePoint={(id) => {
                  notes.setPageSelection(id);
                  const existing = notes.notesByKnowledgePointId[id];
                  if (existing && !notes.noteDrafts[id]) { notes.syncNoteRecord(existing); return; }
                  if (!existing && currentContext?.knowledgePointId === id && app.user) {
                    void notes.ensureForContext(app.user.id, { ...currentContext, source: "notes" }).then((n) => { if (n) notes.setPageSelection(n.knowledge_point_id); });
                  }
                }}
                onDraftTitleChange={(v) => { if (notes.pageSelection) notes.updateDraftTitle(notes.pageSelection, v); }}
                onDraftContentChange={(v) => { if (notes.pageSelection) notes.updateDraftContent(notes.pageSelection, v); }}
                onRetrySave={() => { if (notes.pageSelection) void notes.saveByKnowledgePointId(notes.pageSelection); }}
                onRequestAgentDraft={() => { if (notes.pageSelection && app.user) void notes.requestAgentDraft(notes.pageSelection, app.user.id, currentContext, lastAttemptId); }}
                onCreateCurrentNote={() => { if (currentContext && app.user) void notes.ensureForContext(app.user.id, { ...currentContext, source: "notes" }).then((n) => { if (n) notes.setPageSelection(n.knowledge_point_id); }); }}
              />
            </section>

            <section className={screenClassName(visibleRoute === "settings")} aria-label="设置页">
              <SettingsPage
                settingsTab={settings.settingsTab}
                form={settings.form}
                isDirty={settingsDirty}
                canSave={Boolean(app.user && settingsDirty && settings.saveState !== "saving" && (settings.settingsTab === "learning" || settings.settingsTab === "notifications"))}
                saveState={settings.saveState}
                saveErrorMessage={settings.saveErrorMessage}
                userLoaded={Boolean(app.user)}
                diagnostics={{ apiBaseUrl: API_BASE_URL, apiStatus: apiStatusLabel, userId: app.user?.id ?? null, planId: currentPlanId, currentStage: dashboard?.current_stage ?? session?.context_snapshot.current_stage ?? null, todayReviewCount: dashboard?.today_review_count ?? 0, resumeAvailable: dashboard?.resume_available ?? false }}
                environmentDoctor={environmentDoctor}
                localUsersState={app.localUsersState}
                userDataSummaryState={app.userDataSummaryState}
                dataActionState={app.dataActionState}
                dataActionMessage={app.dataActionMessage}
                onSettingsTabChange={settings.setTab}
                onFieldChange={settings.updateField}
                onSave={() => void handleSaveSettings()}
                onRefreshEnvironmentDoctor={() => void refreshEnvironmentDoctor()}
                onRefreshLocalData={() => {
                  void app.loadLocalUsers();
                  void app.loadUserDataSummary();
                }}
                onSwitchLocalUser={(item) => void handleSwitchLocalUser(item)}
                onExportUserData={() => void handleExportUserData()}
                onResetUserData={() => void handleResetUserData()}
                onDeleteUserData={() => void handleDeleteUserData()}
              />
            </section>
          </div>

          <div className={notes.drawerOpen ? "drawer-scrim open" : "drawer-scrim"} onClick={() => void closeDrawers()}></div>

          {notes.drawerOpen && (
            <NoteDrawer drawerKnowledgePointId={drawerKnowledgePointId} drawerNote={drawerNote} drawerDraft={drawerDraft} userId={app.user?.id} lastAttemptId={lastAttemptId} />
          )}

        </section>
      </section>
    </main>
  );
}

function buildLearningNoteContext(session: LearningSessionResponse | null): NoteContext | null {
  if (!session) return null;
  return {
    knowledgePointId: session.context_snapshot.KnowledgePoint.id,
    knowledgePointTitle: session.context_snapshot.KnowledgePoint.title,
    source: "learning",
    sessionId: session.session_id,
    language: session.context_snapshot.RuntimeProfile.language,
  };
}

export default App;
