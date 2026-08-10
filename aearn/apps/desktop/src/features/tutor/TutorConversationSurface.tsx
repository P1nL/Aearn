import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";

import {
  acceptTutorConversationInput,
  acceptTutorFirstTurn,
  acceptTutorRunInput,
  buildTutorRunEventsUrl,
  correctTutorMemory,
  deleteTutorMemory,
  dismissTutorInbox,
  fetchTutorActivity,
  fetchTutorConversationHistory,
  fetchTutorInbox,
  fetchTutorMemory,
  fetchTutorPlanRevisions,
  fetchTutorPreferences,
  markTutorInboxRead,
  rollbackTutorPlan,
  updateTutorPreferences,
} from "../../api";
import { TutorActivityPanel } from "./TutorActivityPanel";
import { TutorMemoryPanel } from "./TutorMemoryPanel";
import { TutorPlanPreferencesPanel } from "./TutorPlanPreferencesPanel";
import { useTutorSSE } from "../../hooks/useTutorSSE";
import { getErrorInfo } from "../../lib/errorMessages";
import type {
  ApiError,
  TutorActivityItem,
  TutorConversationHistoryResponse,
  TutorForegroundRun,
  TutorHistoryItem,
  TutorInboxItem,
  TutorMemoryItem,
  TutorPlanRevisionList,
  TutorPreferences,
  TutorPublicProcess,
  TutorRunStatus,
  TutorSseEvent,
  UserProfile,
} from "../../types";

export type TutorConversationSurfaceProps = {
  user: UserProfile | null;
  enabled?: boolean;
  isActive?: boolean;
  selectedConversationId: string | null;
  onSelectConversation: (conversationId: string | null) => void;
  onConversationsChanged?: () => void;
  mode?: "general" | "plan_drafting";
  showControls?: boolean;
};

type ControlsStatus = "idle" | "loading" | "ready" | "error";
type HistoryStatus = "idle" | "loading" | "ready" | "error";
type ComposerMode = "ordinary" | "continuation";
type PreferenceUpdate = {
  inferredMemoryEnabled?: boolean;
  expectedMemorySettingVersion?: string;
  proactivePaused?: boolean;
};
type ScrollAnchor = { top: number; height: number };

const HISTORY_PAGE_SIZE = 40;
const GENERAL_EXAMPLES = ["帮我理清闭包和作用域", "我想系统复习 DOM 事件", "这个报错我不知道从哪里开始看"] as const;

export function TutorConversationSurface({
  user,
  enabled = false,
  isActive = true,
  selectedConversationId,
  onSelectConversation,
  onConversationsChanged,
  mode = "general",
  showControls = true,
}: TutorConversationSurfaceProps) {
  const [timeline, setTimeline] = useState<TutorHistoryItem[]>([]);
  const [historyStatus, setHistoryStatus] = useState<HistoryStatus>("idle");
  const [historyError, setHistoryError] = useState<{ code: string; message: string } | null>(null);
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [historyHasMore, setHistoryHasMore] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [activeRun, setActiveRun] = useState<TutorForegroundRun | null>(null);
  const [activeRunConversationId, setActiveRunConversationId] = useState<string | null>(null);
  const [composerText, setComposerText] = useState("");
  const [composerMode, setComposerMode] = useState<ComposerMode>("ordinary");
  const [composerStatus, setComposerStatus] = useState<"idle" | "submitting">("idle");
  const [composerError, setComposerError] = useState<{ code: string; message: string } | null>(null);
  const [streamError, setStreamError] = useState<ApiError | null>(null);
  const [openProcessRuns, setOpenProcessRuns] = useState<Record<string, boolean>>({});
  const [controlsStatus, setControlsStatus] = useState<ControlsStatus>("idle");
  const [controlsError, setControlsError] = useState<string | null>(null);
  const [activity, setActivity] = useState<TutorActivityItem[]>([]);
  const [inbox, setInbox] = useState<TutorInboxItem[]>([]);
  const [memory, setMemory] = useState<TutorMemoryItem[]>([]);
  const [plans, setPlans] = useState<TutorPlanRevisionList | null>(null);
  const [preferences, setPreferences] = useState<TutorPreferences | null>(null);
  const [busyInboxId, setBusyInboxId] = useState<string | null>(null);
  const [busyMemoryId, setBusyMemoryId] = useState<string | null>(null);
  const [pendingPlanOrPreferenceAction, setPendingPlanOrPreferenceAction] = useState<"rollback" | "memory" | "proactive" | null>(null);

  const userId = user?.id ?? null;
  const mayUseTutor = enabled && isActive && userId !== null;
  const selectedConversationIdRef = useRef<string | null>(selectedConversationId);
  const timelineRef = useRef<HTMLElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const historyRequestRef = useRef<AbortController | null>(null);
  const refreshTimerRef = useRef<number | null>(null);
  const prependAnchorRef = useRef<ScrollAnchor | null>(null);
  const scrollToLatestRef = useRef(false);
  selectedConversationIdRef.current = selectedConversationId;

  const continuationAvailable = activeRun?.status === "waiting_for_input" && activeRun.continuation_kind !== null;
  const streamUrl = mayUseTutor && userId && selectedConversationId && activeRun && activeRunConversationId === selectedConversationId
    ? buildTutorRunEventsUrl(activeRun.run_id, userId)
    : null;

  const mergeChronologicalTimeline = useCallback((items: TutorHistoryItem[], placement: "replace" | "prepend") => {
    const chronological = [...items].reverse();
    setTimeline((current) => {
      const combined = placement === "prepend" ? [...chronological, ...current] : chronological;
      const seen = new Set<string>();
      return combined.filter((item) => {
        const key = `${item.kind}:${item.id}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
    });
  }, []);

  const loadHistory = useCallback(async (
    conversationId: string,
    options: { cursor?: string | null; placement?: "replace" | "prepend"; showLoading?: boolean } = {},
  ): Promise<TutorConversationHistoryResponse | null> => {
    if (!mayUseTutor || !userId || selectedConversationIdRef.current !== conversationId) return null;
    historyRequestRef.current?.abort();
    const controller = new AbortController();
    historyRequestRef.current = controller;
    const placement = options.placement ?? "replace";
    if (options.showLoading) {
      setHistoryStatus("loading");
      setHistoryError(null);
      if (placement === "replace") {
        setTimeline([]);
        setHistoryCursor(null);
        setHistoryHasMore(false);
        setActiveRun(null);
        setActiveRunConversationId(null);
        setOpenProcessRuns({});
      }
    }
    try {
      const response = await fetchTutorConversationHistory({
        userId,
        conversationId,
        limit: HISTORY_PAGE_SIZE,
        cursor: options.cursor,
        signal: controller.signal,
      });
      if (controller.signal.aborted || selectedConversationIdRef.current !== conversationId) return null;
      mergeChronologicalTimeline(response.items, placement);
      if (placement === "replace") {
        setHistoryCursor(response.next_cursor);
        setHistoryHasMore(response.has_more);
        setActiveRun(response.active_run);
        setActiveRunConversationId(response.active_run ? conversationId : null);
        setHistoryStatus("ready");
        scrollToLatestRef.current = true;
      }
      return response;
    } catch (error) {
      if (controller.signal.aborted) return null;
      const info = getErrorInfo(error);
      setHistoryError({ code: info.code, message: info.message });
      setHistoryStatus("error");
      return null;
    } finally {
      if (historyRequestRef.current === controller) historyRequestRef.current = null;
    }
  }, [mayUseTutor, mergeChronologicalTimeline, userId]);

  const refreshCurrentHistory = useCallback(() => {
    const conversationId = selectedConversationIdRef.current;
    if (!conversationId) return;
    void loadHistory(conversationId, { placement: "replace" });
  }, [loadHistory]);

  const scheduleHistoryRefresh = useCallback(() => {
    if (refreshTimerRef.current !== null) return;
    refreshTimerRef.current = window.setTimeout(() => {
      refreshTimerRef.current = null;
      refreshCurrentHistory();
    }, 80);
  }, [refreshCurrentHistory]);

  const loadControls = useCallback(async (signal?: AbortSignal) => {
    if (!userId || !mayUseTutor || !showControls) {
      setControlsStatus("idle");
      return;
    }
    setControlsStatus("loading");
    setControlsError(null);
    try {
      const [nextActivity, nextInbox, nextMemory, nextPlans, nextPreferences] = await Promise.all([
        fetchTutorActivity(userId, signal),
        fetchTutorInbox(userId, signal),
        fetchTutorMemory(userId, signal),
        fetchTutorPlanRevisions(userId, signal),
        fetchTutorPreferences(userId, signal),
      ]);
      if (signal?.aborted) return;
      setActivity(nextActivity);
      setInbox(nextInbox);
      setMemory(nextMemory);
      setPlans(nextPlans);
      setPreferences(nextPreferences);
      setControlsStatus("ready");
    } catch (error) {
      if (signal?.aborted) return;
      const info = getErrorInfo(error);
      setControlsError(info.message);
      setControlsStatus("error");
    }
  }, [mayUseTutor, userId]);

  const handleTutorEvent = useCallback((event: TutorSseEvent) => {
    scheduleHistoryRefresh();
    if (event.type === "done" || event.type === "error" || event.type === "activity") {
      void loadControls();
      onConversationsChanged?.();
    }
  }, [loadControls, onConversationsChanged, scheduleHistoryRefresh]);

  const stream = useTutorSSE(streamUrl, {
    enabled: Boolean(streamUrl),
    maxReconnectAttempts: 2,
    onEvent: handleTutorEvent,
    onError: setStreamError,
  });

  useEffect(() => {
    // The transport hook cleans the previous endpoint when the selected conversation changes.
    historyRequestRef.current?.abort();
    if (refreshTimerRef.current !== null) {
      window.clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }
    setComposerText("");
    setComposerMode("ordinary");
    setComposerStatus("idle");
    setComposerError(null);
    setStreamError(null);
    setOpenProcessRuns({});

    if (!mayUseTutor || !userId || !selectedConversationId) {
      setTimeline([]);
      setHistoryStatus("idle");
      setHistoryError(null);
      setHistoryCursor(null);
      setHistoryHasMore(false);
      setActiveRun(null);
      setActiveRunConversationId(null);
      return;
    }
    void loadHistory(selectedConversationId, { placement: "replace", showLoading: true });
  }, [loadHistory, mayUseTutor, selectedConversationId, userId]);

  useEffect(() => {
    if (!mayUseTutor || !userId) return;
    const controller = new AbortController();
    void loadControls(controller.signal);
    return () => controller.abort();
  }, [loadControls, mayUseTutor, userId]);

  useEffect(() => () => {
    historyRequestRef.current?.abort();
    if (refreshTimerRef.current !== null) window.clearTimeout(refreshTimerRef.current);
  }, []);

  useEffect(() => {
    const element = timelineRef.current;
    if (!element) return;
    if (prependAnchorRef.current) {
      const anchor = prependAnchorRef.current;
      element.scrollTop = anchor.top + (element.scrollHeight - anchor.height);
      prependAnchorRef.current = null;
      return;
    }
    if (scrollToLatestRef.current) {
      element.scrollTop = element.scrollHeight;
      scrollToLatestRef.current = false;
    }
  }, [timeline]);

  async function loadOlderHistory() {
    if (!selectedConversationId || !historyCursor || loadingOlder) return;
    const element = timelineRef.current;
    if (element) prependAnchorRef.current = { top: element.scrollTop, height: element.scrollHeight };
    setLoadingOlder(true);
    try {
      const response = await loadHistory(selectedConversationId, { cursor: historyCursor, placement: "prepend" });
      if (response) {
        setHistoryCursor(response.next_cursor);
        setHistoryHasMore(response.has_more);
      }
    } finally {
      setLoadingOlder(false);
    }
  }

  async function submitComposer() {
    const content = composerText.trim();
    if (!content || !mayUseTutor || !userId || composerStatus === "submitting") return;

    setComposerStatus("submitting");
    setComposerError(null);
    try {
      const accepted = composerMode === "continuation" && continuationAvailable && activeRun
        ? await acceptTutorRunInput({
            userId,
            runId: activeRun.run_id,
            content,
            clientActionId: createTutorActionId("tutor-continuation-input"),
          })
        : selectedConversationId
          ? await acceptTutorConversationInput({
              userId,
              conversationId: selectedConversationId,
              content,
              clientActionId: createTutorActionId("tutor-conversation-input"),
              ...(mode === "plan_drafting"
                ? { learningScope: { scope_kind: "plan_drafting" as const, task_kind: "plan_drafting" as const } }
                : {}),
            })
          : await acceptTutorFirstTurn({
              userId,
              content,
              clientActionId: createTutorActionId("tutor-first-turn"),
            });

      setComposerText("");
      setComposerMode("ordinary");
      setActiveRun({
        run_id: accepted.run.run_id,
        status: accepted.run.status,
        continuation_kind: accepted.run.continuation_kind,
      });
      setActiveRunConversationId(accepted.conversation_id);
      onConversationsChanged?.();
      if (selectedConversationId !== accepted.conversation_id) {
        onSelectConversation(accepted.conversation_id);
      } else {
        scrollToLatestRef.current = true;
        refreshCurrentHistory();
      }
    } catch (error) {
      const info = getErrorInfo(error);
      setComposerError({ code: info.code, message: info.message });
      refreshCurrentHistory();
    } finally {
      setComposerStatus("idle");
    }
  }

  async function handleMarkInboxRead(inboxId: string) {
    if (!userId) return;
    setBusyInboxId(inboxId);
    try {
      const item = await markTutorInboxRead({ userId, inboxId, clientActionId: createTutorActionId("tutor-inbox-read") });
      setInbox((current) => current.map((entry) => (entry.inbox_id === item.inbox_id ? item : entry)));
    } finally {
      setBusyInboxId(null);
    }
  }

  async function handleDismissInbox(inboxId: string) {
    if (!userId) return;
    setBusyInboxId(inboxId);
    try {
      const item = await dismissTutorInbox({ userId, inboxId, clientActionId: createTutorActionId("tutor-inbox-dismiss") });
      setInbox((current) => current.filter((entry) => entry.inbox_id !== item.inbox_id));
    } finally {
      setBusyInboxId(null);
    }
  }

  async function handleCorrectMemory(entryId: string, statement: string) {
    if (!userId) return;
    setBusyMemoryId(entryId);
    try {
      const corrected = await correctTutorMemory({
        userId,
        entryId,
        statement,
        clientActionId: createTutorActionId("tutor-memory-correct"),
      });
      setMemory((current) => [...current.filter((entry) => entry.entry_id !== entryId), corrected]);
    } finally {
      setBusyMemoryId(null);
    }
  }

  async function handleDeleteMemory(entryId: string) {
    if (!userId) return;
    setBusyMemoryId(entryId);
    try {
      await deleteTutorMemory({ userId, entryId, clientActionId: createTutorActionId("tutor-memory-delete") });
      setMemory((current) => current.filter((entry) => entry.entry_id !== entryId));
    } finally {
      setBusyMemoryId(null);
    }
  }

  async function handleRollbackPlan() {
    if (!userId) return;
    setPendingPlanOrPreferenceAction("rollback");
    try {
      await rollbackTutorPlan({ userId, clientActionId: createTutorActionId("tutor-plan-rollback") });
      await loadControls();
    } finally {
      setPendingPlanOrPreferenceAction(null);
    }
  }

  async function handleUpdatePreferences(update: PreferenceUpdate) {
    if (!userId) return;
    const action = update.proactivePaused === undefined ? "memory" : "proactive";
    setPendingPlanOrPreferenceAction(action);
    try {
      const nextPreferences = await updateTutorPreferences({
        userId,
        clientActionId: createTutorActionId("tutor-preferences"),
        ...update,
      });
      setPreferences(nextPreferences);
    } finally {
      setPendingPlanOrPreferenceAction(null);
    }
  }

  if (!user) {
    return (
      <section className="tutor-workspace tutor-workspace-boundary" aria-labelledby="tutor-workspace-title">
        <p className="tutor-panel-eyebrow">Tutor 工作台</p>
        <h1 id="tutor-workspace-title">先选择学习者</h1>
        <p>完成本地学习者建档后，才能加载个人的 Tutor 对话、学习记录和计划控制。</p>
      </section>
    );
  }

  if (!enabled) {
    return (
      <section className="tutor-workspace tutor-workspace-boundary" aria-labelledby="tutor-workspace-title">
        <p className="tutor-panel-eyebrow">预切换工作台</p>
        <h1 id="tutor-workspace-title">Tutor 工作台已经就绪</h1>
        <p>它仍在等待服务器权威切换。当前学习页和既有 Graph 流程保持不变，不会因打开此组件自动切换。</p>
      </section>
    );
  }

  const planning = mode === "plan_drafting";
  const planningIdle = planning
    && historyStatus === "ready"
    && timeline.length === 0
    && activeRun === null
    && historyError === null;
  const workspaceClassName = showControls
    ? "tutor-workspace"
    : `tutor-workspace tutor-conversation-only${planningIdle ? " tutor-conversation-idle" : ""}`;
  const title = selectedConversationId ? "当前学习对话" : "新对话";
  const composerLabel = composerMode === "continuation"
    ? "继续完成这项确认"
    : planning
      ? "告诉 Tutor 你的目标或调整意见"
      : selectedConversationId
        ? "继续当前对话"
        : "从你的学习目标开始";
  const composerHint = composerMode === "continuation"
    ? "此输入仅用于服务器明确要求的继续确认。"
    : planning
      ? "普通消息会创建新的有限 plan_drafting TurnRun；正式计划只来自已验证的类型化草案。"
      : "普通消息会创建新的有限 TurnRun；当前会话历史会被安全保留。";
  const composerSubmitLabel = composerStatus === "submitting"
    ? "正在确认输入……"
    : composerMode === "continuation"
      ? "提交确认"
      : selectedConversationId
        ? "发送消息"
        : "开始对话";
  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      void submitComposer();
    }
  }

  return (
    <main
      className={workspaceClassName}
      aria-label={planning ? "学习计划对话" : undefined}
      aria-labelledby={planning ? undefined : "tutor-workspace-title"}
    >
      <section className="tutor-main-column">
        {!planning && (
          <header className="tutor-hero">
            <div>
              <p className="tutor-panel-eyebrow">Tutor 学习对话</p>
              <h1 id="tutor-workspace-title">{title}</h1>
              <p>服务端保存可见对话与公开处理过程。普通消息始终从新的、有限的处理单元开始。</p>
            </div>
            <div className="tutor-run-summary" aria-live="polite">
              <span>当前状态</span>
              <strong>{activeRun ? displayRunStatus(activeRun.status) : selectedConversationId ? "没有进行中的处理" : "等待你的第一条目标"}</strong>
              {activeRun && <small>{activeRun.continuation_kind ? "等待明确的继续确认" : "正在使用当前公开状态"}</small>}
              {streamUrl && <small>流游标：{stream.cursor}</small>}
            </div>
          </header>
        )}

        {streamError && (
          <div className="tutor-inline-error tutor-stream-error" role="alert">
            <div>
              <strong>{streamError.code}</strong>
              <span>{streamError.message}</span>
            </div>
            {streamError.recoverable && streamUrl && (
              <button className="tutor-text-button" type="button" onClick={stream.retry}>重新连接</button>
            )}
          </div>
        )}
        {composerError && (
          <div className="tutor-inline-error" role="alert">
            <strong>{composerError.code}</strong>
            <span>{composerError.message}</span>
          </div>
        )}

        <section className={`tutor-timeline${planning ? " tutor-chatgpt-timeline" : ""}`} ref={timelineRef} aria-label="Tutor 对话时间线" aria-busy={historyStatus === "loading"}>
          {historyHasMore && (
            <button className="tutor-load-earlier" type="button" onClick={() => void loadOlderHistory()} disabled={loadingOlder}>
              {loadingOlder ? "正在加载更早记录……" : "加载更早记录"}
            </button>
          )}
          {historyStatus === "loading" && timeline.length === 0 && (
            <div className="tutor-empty-timeline"><strong>正在恢复对话记录……</strong></div>
          )}
          {historyStatus === "error" && historyError && (
            <div className="tutor-inline-error" role="alert">
              <div><strong>{historyError.code}</strong><span>{historyError.message}</span></div>
              {selectedConversationId && <button className="tutor-text-button" type="button" onClick={refreshCurrentHistory}>重试</button>}
            </div>
          )}
          {historyStatus !== "loading" && timeline.length === 0 && !historyError && !planning && (
            <div className="tutor-empty-timeline">
              <strong>{selectedConversationId ? "这里还没有可见记录" : "可以从一个模糊目标开始"}</strong>
              <p>{selectedConversationId ? "服务器会在有可见输入或回复后保留时间线。" : "例如：理解闭包、准备 JavaScript DOM 项目，或针对某个报错调整学习方向。"}</p>
            </div>
          )}
          {timeline.map((item) => item.kind === "process"
            ? (
              <PublicProcessDisclosure
                key={`process:${item.id}`}
                process={item}
                open={Boolean(openProcessRuns[item.run_id])}
                onToggle={() => setOpenProcessRuns((current) => ({ ...current, [item.run_id]: !current[item.run_id] }))}
              />
            )
            : (
              <article className={`tutor-timeline-entry ${item.role === "learner" ? "learner" : "tutor"}`} key={`message:${item.id}`}>
                <span className="tutor-timeline-label">{item.role === "learner" ? "你" : "Tutor"}</span>
                <div><p>{item.content}</p></div>
              </article>
            ))}
        </section>

        {continuationAvailable && (
          <section className="tutor-continuation-card" aria-label="继续当前确认">
            <div>
              <strong>需要你的确认后才能继续</strong>
              <span>只有这一类服务器明确授权的等待状态会复用当前 run。</span>
            </div>
            <button className="tutor-compact-button" type="button" onClick={() => { setComposerMode("continuation"); composerRef.current?.focus(); }}>
              继续确认
            </button>
          </section>
        )}

        {planning ? (
          <div className={`tutor-chatgpt-composer-area${planningIdle ? " idle" : ""}`}>
            <form className="tutor-composer tutor-composer-chatgpt" onSubmit={(event) => { event.preventDefault(); void submitComposer(); }}>
              <label className="visually-hidden" htmlFor="tutor-composer-input">{composerLabel}</label>
              {composerMode === "continuation" && (
                <div className="tutor-composer-mode" role="status">
                  <span>正在使用已授权的继续确认输入。</span>
                  <button className="tutor-text-button" type="button" onClick={() => setComposerMode("ordinary")}>改为普通消息</button>
                </div>
              )}
              <div className="tutor-composer-chatgpt-shell">
                <textarea
                  ref={composerRef}
                  id="tutor-composer-input"
                  value={composerText}
                  rows={2}
                  maxLength={16_000}
                  placeholder={composerMode === "continuation" ? "输入服务器请求的确认或结果。" : "描述你想学习什么，或回答 Tutor 的问题"}
                  disabled={!mayUseTutor || composerStatus === "submitting"}
                  onChange={(event) => setComposerText(event.target.value)}
                  onKeyDown={handleComposerKeyDown}
                />
                <button
                  className="tutor-composer-send"
                  type="submit"
                  aria-label={composerSubmitLabel}
                  title={composerSubmitLabel}
                  disabled={composerStatus === "submitting" || composerText.trim().length === 0}
                >
                  <span aria-hidden="true">↑</span>
                </button>
              </div>
              {!planningIdle ? <p className="tutor-composer-hint">Aearn Tutor 可能会犯错，请核对生成的计划路线。按 Ctrl / ⌘ + Enter 可发送。</p> : null}
            </form>
          </div>
        ) : (
          <form className="tutor-composer" onSubmit={(event) => { event.preventDefault(); void submitComposer(); }}>
            <label htmlFor="tutor-composer-input">{composerLabel}</label>
            {composerMode === "continuation" && (
              <div className="tutor-composer-mode" role="status">
                <span>正在使用已授权的继续确认输入。</span>
                <button className="tutor-text-button" type="button" onClick={() => setComposerMode("ordinary")}>改为普通消息</button>
              </div>
            )}
            <textarea
              ref={composerRef}
              id="tutor-composer-input"
              value={composerText}
              rows={4}
              maxLength={16_000}
              placeholder="例如：我会写基础 JavaScript，但总弄不清闭包里的变量什么时候会保留。"
              disabled={!mayUseTutor || composerStatus === "submitting"}
              onChange={(event) => setComposerText(event.target.value)}
              onKeyDown={handleComposerKeyDown}
            />
            <div className="tutor-composer-footer">
              <div className="tutor-goal-examples" aria-label="目标示例">
                {GENERAL_EXAMPLES.map((example) => (
                  <button key={example} type="button" onClick={() => setComposerText(example)} disabled={composerStatus === "submitting"}>{example}</button>
                ))}
              </div>
              <button className="tutor-primary-button" type="submit" disabled={composerStatus === "submitting" || composerText.trim().length === 0}>
                {composerSubmitLabel}
              </button>
            </div>
            <p className="tutor-composer-hint">{composerHint} 按 Ctrl / ⌘ + Enter 可发送。</p>
          </form>
        )}
      </section>

      {showControls && <aside className="tutor-side-column" aria-label="Tutor 学习控制">
        <TutorActivityPanel
          activity={activity}
          inbox={inbox}
          loading={controlsStatus === "loading"}
          errorMessage={controlsStatus === "error" ? controlsError : null}
          busyInboxId={busyInboxId}
          onRetry={() => void loadControls()}
          onMarkRead={handleMarkInboxRead}
          onDismiss={handleDismissInbox}
        />
        <TutorMemoryPanel
          memory={memory}
          loading={controlsStatus === "loading"}
          errorMessage={controlsStatus === "error" ? controlsError : null}
          busyEntryId={busyMemoryId}
          onRetry={() => void loadControls()}
          onCorrect={handleCorrectMemory}
          onDelete={handleDeleteMemory}
        />
        <TutorPlanPreferencesPanel
          plans={plans}
          preferences={preferences}
          loading={controlsStatus === "loading"}
          errorMessage={controlsStatus === "error" ? controlsError : null}
          pendingAction={pendingPlanOrPreferenceAction}
          onRetry={() => void loadControls()}
          onRollback={handleRollbackPlan}
          onUpdatePreferences={handleUpdatePreferences}
        />
      </aside>}
    </main>
  );
}

type PublicProcessDisclosureProps = {
  process: TutorPublicProcess;
  open: boolean;
  onToggle: () => void;
};

function PublicProcessDisclosure({ process, open, onToggle }: PublicProcessDisclosureProps) {
  const detailId = `tutor-public-process-${process.run_id}`;
  const status = displayPublicProcessStatus(process);
  const duration = formatPublicDuration(process.elapsed_seconds);

  return (
    <section className={`tutor-public-process ${process.display_state}`} aria-label={status}>
      <button
        className="tutor-public-process-toggle"
        type="button"
        aria-expanded={open}
        aria-controls={detailId}
        aria-label={`公开处理过程：${status}。${open ? "收起详情" : "展开详情"}`}
        onClick={onToggle}
      >
        <span className="tutor-public-process-indicator" aria-hidden="true" />
        <span className="tutor-public-process-summary">
          <strong>{status}</strong>
          <small>{process.display_state === "thinking" ? "公开处理过程可展开查看已完成步骤" : `已处理 ${duration}`}</small>
        </span>
        <span className="tutor-public-process-chevron" aria-hidden="true">⌄</span>
      </button>
      <div id={detailId} className="tutor-public-process-details" hidden={!open}>
        <strong>公开处理过程</strong>
        {process.steps.length > 0 ? (
          <ol className="tutor-public-process-steps">
            {process.steps.map((step) => (
              <li className={`tutor-public-process-step ${step.state}`} key={`${process.run_id}:${step.key}`}>
                <span aria-hidden="true" />
                <span>{step.label}</span>
              </li>
            ))}
          </ol>
        ) : (
          <p>暂时没有可展示的公开步骤。</p>
        )}
      </div>
    </section>
  );
}

function displayRunStatus(status: TutorRunStatus): string {
  return {
    queued: "正在排队",
    leased: "正在准备",
    running: "正在思考",
    waiting_for_input: "等待你的确认",
    waiting_for_capability: "正在等待已授权的能力",
    awaiting_effect_commit: "正在确认学习更新",
    completed: "已完成",
    model_unavailable: "模型暂不可用",
    blocked_policy: "当前操作未获允许",
    budget_exhausted: "本次处理已达到安全限制",
    cancelled: "已根据新消息更新",
    failed: "未能安全完成",
  }[status];
}

function displayPublicProcessStatus(process: TutorPublicProcess): string {
  if (process.display_state === "thinking") return "正在思考";
  if (process.display_state === "completed") return `已处理 ${formatPublicDuration(process.elapsed_seconds)}`;
  if (process.display_state === "superseded") return "已根据你的新消息更新本轮处理";
  return "本轮处理暂不可用";
}

function formatPublicDuration(elapsedSeconds: number): string {
  const seconds = Math.max(0, Math.min(3_600, elapsedSeconds));
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return remainder > 0 ? `${minutes} 分 ${remainder} 秒` : `${minutes} 分`;
}

function createTutorActionId(prefix: string): string {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}:${random}`;
}
