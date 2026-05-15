import { startTransition, useEffect, useState, type FormEvent } from "react";

import {
  createNote,
  fetchApiHealth,
  fetchLanguageCourses,
  fetchNotes,
  requestNoteAgentDraft,
  startLearningSession,
  updateNote,
} from "./api";
import type {
  ApiHealthState,
  AppRoute,
  ConversationMessage,
  NavGroupKey,
  NoteContext,
  SessionState,
  SettingsKey,
} from "./appTypes";
import { ApiHealthChip } from "./components/ApiHealthChip";
import { SidebarNav } from "./components/SidebarNav";
import { SideContext } from "./components/SideContext";
import {
  HOME_BASE_MESSAGES,
  NAV_DEFAULTS,
  ONBOARDING_MESSAGES,
  REVIEW_BASE_MESSAGES,
  ROUTE_META,
} from "./lib/appContent";
import { getCrumbLabel, screenClassName } from "./lib/desktopLabels";
import { applyKnowledgePointUpdate, computeSidebarProgress, createMessage, markKnowledgePointLearning } from "./lib/learningHelpers";
import { LearningWorkspacePage } from "./pages/LearningWorkspacePage";
import { NotesPage } from "./pages/NotesPage";
import { OnboardingPage } from "./pages/OnboardingPage";
import { ReviewPage } from "./pages/ReviewPage";
import { SettingsPage } from "./pages/SettingsPage";
import type {
  CreatedPlanResponse,
  LanguageCourse,
  LearningSessionResponse,
  NoteRecord,
  RunExerciseResponse,
  SubmitExerciseResponse,
  UserProfile,
} from "./types";
import { ApiRequestError } from "./types";

type NoteDraftState = {
  title: string;
  content: string;
  status: "加载中" | "未保存" | "保存中" | "已保存" | "保存失败";
  errorMessage: string | null;
};

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
  const [composerInput, setComposerInput] = useState("");
  const [homeConversation, setHomeConversation] = useState<ConversationMessage[]>([]);
  const [reviewConversation, setReviewConversation] = useState<ConversationMessage[]>([]);
  const [resetNonce, setResetNonce] = useState(0);

  const [notesLoadState, setNotesLoadState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [notesErrorMessage, setNotesErrorMessage] = useState<string | null>(null);
  const [notesList, setNotesList] = useState<NoteRecord[]>([]);
  const [notesByKnowledgePointId, setNotesByKnowledgePointId] = useState<Record<string, NoteRecord>>({});
  const [noteDrafts, setNoteDrafts] = useState<Record<string, NoteDraftState>>({});
  const [noteAssistBusyByKnowledgePointId, setNoteAssistBusyByKnowledgePointId] = useState<Record<string, boolean>>({});
  const [noteDrawerContext, setNoteDrawerContext] = useState<NoteContext | null>(null);
  const [reviewNoteContext, setReviewNoteContext] = useState<NoteContext | null>(null);
  const [notesPageSelection, setNotesPageSelection] = useState<string | null>(null);

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
  const currentSessionNoteContext = buildLearningNoteContext(session);
  const currentContext = currentSessionNoteContext ?? reviewNoteContext;
  const drawerKnowledgePointId = noteDrawerContext?.knowledgePointId ?? null;
  const drawerNote = drawerKnowledgePointId ? notesByKnowledgePointId[drawerKnowledgePointId] ?? null : null;
  const drawerDraft = drawerKnowledgePointId ? noteDrafts[drawerKnowledgePointId] ?? null : null;
  const selectedNote = notesPageSelection ? notesByKnowledgePointId[notesPageSelection] ?? null : null;
  const selectedDraft = notesPageSelection ? noteDrafts[notesPageSelection] ?? null : null;
  const activeEditorKnowledgePointId = noteDrawerOpen ? drawerKnowledgePointId : visibleRoute === "notes" ? notesPageSelection : null;
  const canOpenNoteDrawer = Boolean(user && ((visibleRoute === "home" && currentSessionNoteContext) || (visibleRoute === "review" && reviewNoteContext)));

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

  async function goToRoute(route: AppRoute) {
    const closed = await closeDrawers();
    if (!closed) {
      return;
    }
    setActiveRoute(route);
  }

  async function closeDrawers() {
    if (!noteDrawerOpen || !drawerKnowledgePointId) {
      setNoteDrawerOpen(false);
      return true;
    }
    const draft = noteDrafts[drawerKnowledgePointId];
    if (draft?.status === "未保存") {
      const saved = await saveNoteByKnowledgePointId(drawerKnowledgePointId);
      if (!saved) {
        return false;
      }
    }
    setNoteDrawerOpen(false);
    return true;
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
    setActiveRoute("onboarding");
    setResetNonce((current) => current + 1);
    setNotesLoadState("idle");
    setNotesErrorMessage(null);
    setNotesList([]);
    setNotesByKnowledgePointId({});
    setNoteDrafts({});
    setNoteAssistBusyByKnowledgePointId({});
    setNoteDrawerContext(null);
    setReviewNoteContext(null);
    setNotesPageSelection(null);
    setNoteDrawerOpen(false);
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

  function setDraftStatus(
    knowledgePointId: string,
    status: NoteDraftState["status"],
    errorMessage: string | null = null,
  ) {
    setNoteDrafts((current) => {
      const previous = current[knowledgePointId];
      if (!previous) {
        return current;
      }
      return {
        ...current,
        [knowledgePointId]: {
          ...previous,
          status,
          errorMessage,
        },
      };
    });
  }

  function syncNoteRecord(note: NoteRecord, draftStatus: NoteDraftState["status"] = "已保存") {
    setNotesByKnowledgePointId((current) => ({
      ...current,
      [note.knowledge_point_id]: note,
    }));
    setNotesList((current) => sortNotesByUpdatedAt(upsertNote(current, note)));
    setNoteDrafts((current) => ({
      ...current,
      [note.knowledge_point_id]: {
        title: note.title,
        content: note.content_markdown,
        status: draftStatus,
        errorMessage: null,
      },
    }));
  }

  async function loadNotesIndex(signal?: AbortSignal) {
    if (!user) {
      setNotesLoadState("idle");
      setNotesList([]);
      setNotesByKnowledgePointId({});
      return;
    }
    setNotesLoadState("loading");
    setNotesErrorMessage(null);
    try {
      const response = await fetchNotes({ userId: user.id, limit: 50, signal });
      startTransition(() => {
        setNotesList(sortNotesByUpdatedAt(response.items));
        setNotesByKnowledgePointId(Object.fromEntries(response.items.map((item) => [item.knowledge_point_id, item])));
        setNotesLoadState("ready");
        if (response.items.length > 0) {
          setNotesPageSelection((current) => current ?? response.items[0].knowledge_point_id);
        }
      });
    } catch (error) {
      if (signal?.aborted) {
        return;
      }
      setNotesLoadState("error");
      setNotesErrorMessage(formatError(error, "无法读取笔记列表"));
    }
  }

  async function ensureNoteForContext(context: NoteContext): Promise<NoteRecord | null> {
    if (!user) {
      return null;
    }
    setNoteDrafts((current) => ({
      ...current,
      [context.knowledgePointId]: {
        title: current[context.knowledgePointId]?.title ?? context.knowledgePointTitle,
        content: current[context.knowledgePointId]?.content ?? "",
        status: "加载中",
        errorMessage: null,
      },
    }));
    try {
      const response = await fetchNotes({
        userId: user.id,
        knowledgePointId: context.knowledgePointId,
        limit: 1,
      });
      const existing = response.items[0];
      if (existing) {
        syncNoteRecord(existing);
        return existing;
      }
      const created = await createNote({
        userId: user.id,
        knowledgePointId: context.knowledgePointId,
        title: context.knowledgePointTitle,
        contentMarkdown: "",
        source: {
          sessionId: context.sessionId,
          attemptId: context.attemptId,
        },
      });
      syncNoteRecord(created);
      setNotesLoadState("ready");
      return created;
    } catch (error) {
      setNoteDrafts((current) => ({
        ...current,
        [context.knowledgePointId]: {
          title: current[context.knowledgePointId]?.title ?? context.knowledgePointTitle,
          content: current[context.knowledgePointId]?.content ?? "",
          status: "保存失败",
          errorMessage: formatError(error, "无法加载笔记"),
        },
      }));
      return null;
    }
  }

  async function saveNoteByKnowledgePointId(knowledgePointId: string) {
    const note = notesByKnowledgePointId[knowledgePointId];
    const draft = noteDrafts[knowledgePointId];
    if (!note || !draft) {
      return false;
    }
    setDraftStatus(knowledgePointId, "保存中");
    try {
      const updated = await updateNote({
        noteId: note.id,
        title: draft.title,
        contentMarkdown: draft.content,
        isUserEdited: true,
      });
      syncNoteRecord(updated, "已保存");
      return true;
    } catch (error) {
      setDraftStatus(knowledgePointId, "保存失败", formatError(error, "保存失败"));
      return false;
    }
  }

  async function requestAgentDraftForKnowledgePoint(knowledgePointId: string) {
    const note = notesByKnowledgePointId[knowledgePointId];
    if (!note) {
      return;
    }
    setNoteAssistBusyByKnowledgePointId((current) => ({ ...current, [knowledgePointId]: true }));
    try {
      const context =
        (noteDrawerContext?.knowledgePointId === knowledgePointId ? noteDrawerContext : null) ??
        (currentContext?.knowledgePointId === knowledgePointId ? currentContext : null) ??
        {
          knowledgePointId,
          knowledgePointTitle: note.knowledge_point.title,
          source: "notes" as const,
        };
      const updated = await requestNoteAgentDraft({
        noteId: note.id,
        userId: user?.id ?? note.user_id,
        style: "concise",
        focus: "mistake_summary",
        source: {
          sessionId: context.sessionId,
          attemptId: context.attemptId ?? lastSubmit?.attempt_id ?? lastRun?.attempt_id,
        },
      });
      setNotesByKnowledgePointId((current) => ({
        ...current,
        [knowledgePointId]: updated,
      }));
      setNotesList((current) => sortNotesByUpdatedAt(upsertNote(current, updated)));
    } catch (error) {
      setDraftStatus(knowledgePointId, "保存失败", formatError(error, "辅助补全失败"));
    } finally {
      setNoteAssistBusyByKnowledgePointId((current) => ({ ...current, [knowledgePointId]: false }));
    }
  }

  async function handleOpenNoteDrawer() {
    const context = visibleRoute === "review" ? reviewNoteContext : currentSessionNoteContext;
    if (!context) {
      return;
    }
    setNoteDrawerContext(context);
    setNoteDrawerOpen(true);
    const note = await ensureNoteForContext(context);
    if (note) {
      setNotesPageSelection((current) => current ?? note.knowledge_point_id);
    }
  }

  function updateDraftContent(knowledgePointId: string, value: string) {
    setNoteDrafts((current) => {
      const previous = current[knowledgePointId];
      if (!previous) {
        return current;
      }
      return {
        ...current,
        [knowledgePointId]: {
          ...previous,
          content: value,
          status: "未保存",
          errorMessage: null,
        },
      };
    });
  }

  function updateDraftTitle(knowledgePointId: string, value: string) {
    setNoteDrafts((current) => {
      const previous = current[knowledgePointId];
      if (!previous) {
        return current;
      }
      return {
        ...current,
        [knowledgePointId]: {
          ...previous,
          title: value,
          status: "未保存",
          errorMessage: null,
        },
      };
    });
  }

  useEffect(() => {
    const controller = new AbortController();
    void bootstrap(controller.signal);

    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (visibleRoute !== "notes") {
      return;
    }
    const controller = new AbortController();
    void loadNotesIndex(controller.signal);
    return () => controller.abort();
  }, [visibleRoute, user?.id]);

  useEffect(() => {
    if (!activeEditorKnowledgePointId) {
      return;
    }
    const draft = noteDrafts[activeEditorKnowledgePointId];
    if (!draft || draft.status !== "未保存") {
      return;
    }
    const timer = window.setTimeout(() => {
      void saveNoteByKnowledgePointId(activeEditorKnowledgePointId);
    }, 800);
    return () => window.clearTimeout(timer);
  }, [activeEditorKnowledgePointId, noteDrafts]);

  useEffect(() => {
    if (notesList.length === 0) {
      return;
    }
    setNotesPageSelection((current) => {
      if (current && notesByKnowledgePointId[current]) {
        return current;
      }
      return notesList[0]?.knowledge_point_id ?? null;
    });
  }, [notesList, notesByKnowledgePointId]);

  useEffect(() => {
    if (!noteDrawerOpen || !noteDrawerContext) {
      return;
    }
    if (!notesByKnowledgePointId[noteDrawerContext.knowledgePointId]) {
      void ensureNoteForContext(noteDrawerContext);
    }
  }, [noteDrawerOpen, noteDrawerContext?.knowledgePointId]);

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
            onOpenNoteDrawer={() => void handleOpenNoteDrawer()}
          />
        </section>

          <section className={screenClassName(visibleRoute === "review")} aria-label="复习页">
            <ReviewPage
              isActive={visibleRoute === "review"}
              user={user}
              messages={reviewMessages}
              lastSubmit={lastSubmit}
              lastRun={lastRun}
              onActiveNoteContextChange={setReviewNoteContext}
            />
          </section>

          <section className={screenClassName(visibleRoute === "notes")} aria-label="笔记页">
            <NotesPage
              loadState={notesLoadState}
              errorMessage={notesErrorMessage}
              notes={notesList}
              selectedKnowledgePointId={notesPageSelection}
              currentContext={currentContext}
              selectedDraft={selectedDraft}
              assistLoading={Boolean(notesPageSelection && noteAssistBusyByKnowledgePointId[notesPageSelection])}
              onSelectKnowledgePoint={(knowledgePointId) => {
                setNotesPageSelection(knowledgePointId);
                const existing = notesByKnowledgePointId[knowledgePointId];
                if (existing && !noteDrafts[knowledgePointId]) {
                  syncNoteRecord(existing);
                  return;
                }
                if (!existing && currentContext?.knowledgePointId === knowledgePointId) {
                  void ensureNoteForContext({ ...currentContext, source: "notes" }).then((note) => {
                    if (note) {
                      setNotesPageSelection(note.knowledge_point_id);
                    }
                  });
                }
              }}
              onDraftTitleChange={(value) => {
                if (notesPageSelection) {
                  updateDraftTitle(notesPageSelection, value);
                }
              }}
              onDraftContentChange={(value) => {
                if (notesPageSelection) {
                  updateDraftContent(notesPageSelection, value);
                }
              }}
              onRetrySave={() => {
                if (notesPageSelection) {
                  void saveNoteByKnowledgePointId(notesPageSelection);
                }
              }}
              onRequestAgentDraft={() => {
                if (notesPageSelection) {
                  void requestAgentDraftForKnowledgePoint(notesPageSelection);
                }
              }}
              onCreateCurrentNote={() => {
                if (currentContext) {
                  void ensureNoteForContext({ ...currentContext, source: "notes" }).then((note) => {
                    if (note) {
                      setNotesPageSelection(note.knowledge_point_id);
                    }
                  });
                }
              }}
            />
          </section>

          <section className={screenClassName(visibleRoute === "settings")} aria-label="设置页">
            <SettingsPage settingsTab={settingsTab} onSettingsTabChange={setSettingsTab} />
          </section>

          <div className={noteDrawerOpen ? "drawer-scrim open" : "drawer-scrim"} onClick={() => void closeDrawers()}></div>

          {noteDrawerOpen && (
            <section id="noteDrawer" className="drawer open" aria-label="知识点笔记抽屉">
              <div className="drawer-head">
                <div>
                  <h2>{noteDrawerContext?.knowledgePointTitle ?? "知识点笔记"}</h2>
                  {noteDrawerNoteMeta(drawerNote)}
                </div>
                <div className="note-status">
                  <span>{drawerDraft?.status ?? "加载中"}</span>
                  <button className="icon-btn" type="button" aria-label="保存笔记" onClick={() => drawerKnowledgePointId && void saveNoteByKnowledgePointId(drawerKnowledgePointId)}>
                    ✓
                  </button>
                  <button
                    className="btn primary ghost-btn"
                    type="button"
                    disabled={!drawerKnowledgePointId || noteAssistBusyByKnowledgePointId[drawerKnowledgePointId]}
                    onClick={() => drawerKnowledgePointId && void requestAgentDraftForKnowledgePoint(drawerKnowledgePointId)}
                  >
                    {drawerKnowledgePointId && noteAssistBusyByKnowledgePointId[drawerKnowledgePointId] ? "补全中..." : "Agent 补全"}
                  </button>
                </div>
              </div>
              {!drawerDraft ? (
                <div className="tool-card">打开抽屉后会自动加载或创建当前知识点的共享 note。</div>
              ) : (
                <div className="drawer-note-layout">
                  <textarea
                    className="drawer-editor"
                    aria-label="知识点笔记编辑器"
                    value={drawerDraft.content}
                    onChange={(event) => {
                      if (drawerKnowledgePointId) {
                        updateDraftContent(drawerKnowledgePointId, event.target.value);
                      }
                    }}
                  />
                  <aside className="drawer-note-side">
                    <div className="tool-card">
                      <strong>标题</strong>
                      <input
                        className="notes-title-input"
                        value={drawerDraft.title}
                        onChange={(event) => {
                          if (drawerKnowledgePointId) {
                            updateDraftTitle(drawerKnowledgePointId, event.target.value);
                          }
                        }}
                      />
                    </div>
                    <div className="tool-card">
                      <strong>辅助补全</strong>
                      <p>{drawerNote?.agent_draft_content ?? "还没有生成结构化补全建议。会基于当前知识点和最近尝试，只回写 agent_draft_content。"}</p>
                    </div>
                    {drawerDraft.errorMessage && (
                      <div className="tool-card">
                        <strong>保存错误</strong>
                        <p>{drawerDraft.errorMessage}</p>
                      </div>
                    )}
                  </aside>
                </div>
              )}
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
                    aria-label="关闭知识点笔记"
                    aria-controls="noteDrawer"
                    aria-expanded={noteDrawerOpen}
                    onClick={() => {
                      void closeDrawers();
                    }}
                  >
                    <img src="/note.png" alt="" />
                  </button>
                ) : (
                  <button
                    className="btn primary send-btn note-inline-btn"
                    type="button"
                    aria-label="打开知识点笔记"
                    aria-controls="noteDrawer"
                    aria-expanded={noteDrawerOpen}
                    disabled={!canOpenNoteDrawer}
                    onClick={() => {
                      void handleOpenNoteDrawer();
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

function buildLearningNoteContext(session: LearningSessionResponse | null): NoteContext | null {
  if (!session) {
    return null;
  }
  return {
    knowledgePointId: session.context_snapshot.KnowledgePoint.id,
    knowledgePointTitle: session.context_snapshot.KnowledgePoint.title,
    source: "learning",
    sessionId: session.session_id,
    language: session.exercise.runtime_profile.language,
  };
}

function upsertNote(current: NoteRecord[], note: NoteRecord): NoteRecord[] {
  const existingIndex = current.findIndex((item) => item.id === note.id);
  if (existingIndex === -1) {
    return [note, ...current];
  }
  const next = [...current];
  next[existingIndex] = note;
  return next;
}

function sortNotesByUpdatedAt(notes: NoteRecord[]): NoteRecord[] {
  return [...notes].sort((left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime());
}

function formatError(error: unknown, fallback: string): string {
  if (error instanceof ApiRequestError) {
    return `${error.apiError.code}: ${error.apiError.message}`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return fallback;
}

function noteDrawerNoteMeta(note: NoteRecord | null) {
  if (!note) {
    return null;
  }
  return (
    <p className="drawer-note-meta">
      {note.module.title} · {note.course.title}
    </p>
  );
}

export default App;
