import { useEffect, useRef, useState, type FormEvent } from "react";

import { fetchTutorConversations } from "./api";
import { getErrorInfo } from "./lib/errorMessages";
import { HarnessCutoverPage } from "./pages/HarnessCutoverPage";
import { TutorWorkspacePage } from "./pages/TutorWorkspacePage";
import { useAppStore } from "./stores/useAppStore";
import type { TutorConversationSummary } from "./types";

function App() {
  const app = useAppStore();
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [recentConversations, setRecentConversations] = useState<TutorConversationSummary[]>([]);
  const [recentHasMore, setRecentHasMore] = useState(false);
  const [recentStatus, setRecentStatus] = useState<"idle" | "loading" | "error">("idle");
  const [recentError, setRecentError] = useState<string | null>(null);
  const [allConversationsOpen, setAllConversationsOpen] = useState(false);
  const [allConversations, setAllConversations] = useState<TutorConversationSummary[]>([]);
  const [allCursor, setAllCursor] = useState<string | null>(null);
  const [allHasMore, setAllHasMore] = useState(false);
  const [allStatus, setAllStatus] = useState<"idle" | "loading" | "error">("idle");
  const [allError, setAllError] = useState<string | null>(null);
  const allRequestRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void app.bootstrap(controller.signal);
    return () => controller.abort();
  }, [app.bootstrap]);

  async function refreshRecentConversations(signal?: AbortSignal) {
    if (app.activeRoute !== "tutor" || !app.user) {
      setRecentConversations([]);
      setRecentHasMore(false);
      setRecentStatus("idle");
      return;
    }
    setRecentStatus("loading");
    setRecentError(null);
    try {
      const response = await fetchTutorConversations({ userId: app.user.id, limit: 8, signal });
      if (signal?.aborted) return;
      setRecentConversations(response.items);
      setRecentHasMore(response.has_more);
      setRecentStatus("idle");
    } catch (error) {
      if (signal?.aborted) return;
      setRecentConversations([]);
      setRecentHasMore(false);
      setRecentStatus("error");
      setRecentError(getErrorInfo(error).message);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void refreshRecentConversations(controller.signal);
    return () => controller.abort();
  }, [app.activeRoute, app.user?.id]);

  useEffect(() => {
    setSelectedConversationId(null);
    setAllConversationsOpen(false);
    setAllConversations([]);
    setAllCursor(null);
    setAllHasMore(false);
    setAllStatus("idle");
    setAllError(null);
  }, [app.activeRoute, app.user?.id]);

  async function openAllConversations() {
    if (!app.user) return;
    allRequestRef.current?.abort();
    const controller = new AbortController();
    allRequestRef.current = controller;
    setAllConversationsOpen(true);
    setAllStatus("loading");
    setAllError(null);
    try {
      const response = await fetchTutorConversations({ userId: app.user.id, limit: 40, signal: controller.signal });
      if (controller.signal.aborted) return;
      setAllConversations(response.items);
      setAllCursor(response.next_cursor);
      setAllHasMore(response.has_more);
      setAllStatus("idle");
    } catch (error) {
      if (controller.signal.aborted) return;
      setAllStatus("error");
      setAllError(getErrorInfo(error).message);
    } finally {
      if (allRequestRef.current === controller) allRequestRef.current = null;
    }
  }

  async function loadMoreConversations() {
    if (!app.user || !allCursor || allStatus === "loading") return;
    allRequestRef.current?.abort();
    const controller = new AbortController();
    allRequestRef.current = controller;
    setAllStatus("loading");
    setAllError(null);
    try {
      const response = await fetchTutorConversations({
        userId: app.user.id,
        limit: 40,
        cursor: allCursor,
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      setAllConversations((current) => mergeConversations(current, response.items));
      setAllCursor(response.next_cursor);
      setAllHasMore(response.has_more);
      setAllStatus("idle");
    } catch (error) {
      if (controller.signal.aborted) return;
      setAllStatus("error");
      setAllError(getErrorInfo(error).message);
    } finally {
      if (allRequestRef.current === controller) allRequestRef.current = null;
    }
  }

  function selectConversation(conversationId: string | null) {
    setSelectedConversationId(conversationId);
    setAllConversationsOpen(false);
  }

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

        <aside className="sidebar tutor-sidebar" aria-label="Tutor 导航">
          <div className="brand">
            <span className="mark">A</span>
            <span className="brand-name">Aearn Tutor</span>
          </div>
          {app.activeRoute === "tutor" ? (
            <TutorConversationSidebar
              selectedConversationId={selectedConversationId}
              conversations={recentConversations}
              loading={recentStatus === "loading"}
              errorMessage={recentStatus === "error" ? recentError : null}
              showAllAction={recentHasMore}
              onNewConversation={() => selectConversation(null)}
              onSelectConversation={selectConversation}
              onRetry={() => void refreshRecentConversations()}
              onViewAll={() => void openAllConversations()}
            />
          ) : (
            <section className="harness-shell-nav" aria-label="当前入口">
              <strong>{routeLabel}</strong>
              <span>服务器会先核对摘要，再执行任何清理。</span>
            </section>
          )}
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
              <>
                <TutorWorkspacePage
                  user={app.user}
                  enabled
                  isActive
                  selectedConversationId={selectedConversationId}
                  onSelectConversation={selectConversation}
                  onConversationsChanged={() => void refreshRecentConversations()}
                />
                {allConversationsOpen && (
                  <TutorConversationPanel
                    items={allConversations}
                    loading={allStatus === "loading"}
                    errorMessage={allStatus === "error" ? allError : null}
                    hasMore={allHasMore}
                    selectedConversationId={selectedConversationId}
                    onClose={() => setAllConversationsOpen(false)}
                    onSelectConversation={selectConversation}
                    onLoadMore={() => void loadMoreConversations()}
                    onRetry={() => void openAllConversations()}
                  />
                )}
              </>
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

type TutorConversationSidebarProps = {
  selectedConversationId: string | null;
  conversations: TutorConversationSummary[];
  loading: boolean;
  errorMessage: string | null;
  showAllAction: boolean;
  onNewConversation: () => void;
  onSelectConversation: (conversationId: string) => void;
  onRetry: () => void;
  onViewAll: () => void;
};

function TutorConversationSidebar({
  selectedConversationId,
  conversations,
  loading,
  errorMessage,
  showAllAction,
  onNewConversation,
  onSelectConversation,
  onRetry,
  onViewAll,
}: TutorConversationSidebarProps) {
  return (
    <section className="tutor-conversation-sidebar" aria-labelledby="tutor-conversation-nav-title">
      <button className={selectedConversationId === null ? "new-goal active" : "new-goal"} type="button" onClick={onNewConversation}>
        <span>新对话</span>
        <span aria-hidden="true">＋</span>
      </button>
      <div className="tutor-conversation-nav-heading">
        <h2 id="tutor-conversation-nav-title">最近对话</h2>
        <button className="tutor-text-button" type="button" onClick={onRetry} disabled={loading}>刷新</button>
      </div>
      {loading && conversations.length === 0 && <p className="tutor-sidebar-muted">正在读取最近对话……</p>}
      {errorMessage && <p className="tutor-sidebar-error" role="alert">{errorMessage}</p>}
      {!loading && conversations.length === 0 && !errorMessage && <p className="tutor-sidebar-muted">暂时没有已开始的对话。</p>}
      <div className="tutor-conversation-list">
        {conversations.map((conversation) => (
          <button
            className={conversation.conversation_id === selectedConversationId ? "tutor-conversation-item active" : "tutor-conversation-item"}
            type="button"
            key={conversation.conversation_id}
            onClick={() => onSelectConversation(conversation.conversation_id)}
          >
            <span>{conversation.title}</span>
            {conversation.active_run && <small>{displayConversationRunStatus(conversation)}</small>}
          </button>
        ))}
      </div>
      {showAllAction && (
        <button className="tutor-view-all" type="button" onClick={onViewAll}>查看全部对话</button>
      )}
    </section>
  );
}

type TutorConversationPanelProps = {
  items: TutorConversationSummary[];
  loading: boolean;
  errorMessage: string | null;
  hasMore: boolean;
  selectedConversationId: string | null;
  onClose: () => void;
  onSelectConversation: (conversationId: string) => void;
  onLoadMore: () => void;
  onRetry: () => void;
};

function TutorConversationPanel({
  items,
  loading,
  errorMessage,
  hasMore,
  selectedConversationId,
  onClose,
  onSelectConversation,
  onLoadMore,
  onRetry,
}: TutorConversationPanelProps) {
  return (
    <section className="tutor-conversation-panel" role="dialog" aria-modal="true" aria-labelledby="tutor-all-conversations-title">
      <div className="tutor-conversation-panel-card">
        <header>
          <div>
            <p className="tutor-panel-eyebrow">对话历史</p>
            <h2 id="tutor-all-conversations-title">查看全部对话</h2>
          </div>
          <button className="tutor-text-button" type="button" onClick={onClose}>关闭</button>
        </header>
        {errorMessage && (
          <div className="tutor-inline-error" role="alert">
            <span>{errorMessage}</span>
            <button className="tutor-text-button" type="button" onClick={onRetry}>重试</button>
          </div>
        )}
        {loading && items.length === 0 && <p className="tutor-muted-copy">正在读取对话……</p>}
        {!loading && items.length === 0 && !errorMessage && <p className="tutor-muted-copy">还没有已开始的对话。</p>}
        <div className="tutor-conversation-panel-list">
          {items.map((conversation) => (
            <button
              className={conversation.conversation_id === selectedConversationId ? "tutor-conversation-panel-item active" : "tutor-conversation-panel-item"}
              type="button"
              key={conversation.conversation_id}
              onClick={() => onSelectConversation(conversation.conversation_id)}
            >
              <span>{conversation.title}</span>
              <small>{formatConversationActivity(conversation.last_public_activity_at)}{conversation.active_run ? " · " + displayConversationRunStatus(conversation) : ""}</small>
            </button>
          ))}
        </div>
        {hasMore && (
          <button className="tutor-compact-button quiet" type="button" disabled={loading} onClick={onLoadMore}>
            {loading ? "正在加载……" : "加载更多"}
          </button>
        )}
      </div>
    </section>
  );
}

function mergeConversations(current: TutorConversationSummary[], incoming: TutorConversationSummary[]): TutorConversationSummary[] {
  const seen = new Set<string>();
  return [...current, ...incoming].filter((conversation) => {
    if (seen.has(conversation.conversation_id)) return false;
    seen.add(conversation.conversation_id);
    return true;
  });
}

function displayConversationRunStatus(conversation: TutorConversationSummary): string {
  if (!conversation.active_run) return "";
  if (conversation.active_run.status === "waiting_for_input" && conversation.active_run.continuation_kind) return "等待确认";
  if (conversation.active_run.status === "running" || conversation.active_run.status === "leased" || conversation.active_run.status === "queued") return "正在处理";
  return "处理中";
}

function formatConversationActivity(value: string | null): string {
  if (!value) return "时间待同步";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间待同步";
  return date.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default App;
