import { useCallback, useEffect, useRef, useState } from "react";

import {
  acceptTutorConversationInput,
  acceptTutorRunInput,
  buildTutorRunEventsUrl,
  createTutorConversation,
  correctTutorMemory,
  deleteTutorMemory,
  dismissTutorInbox,
  fetchTutorActivity,
  fetchTutorInbox,
  fetchTutorMemory,
  fetchTutorPlanRevisions,
  fetchTutorPreferences,
  fetchTutorRun,
  markTutorInboxRead,
  rollbackTutorPlan,
  updateTutorPreferences,
} from "../api";
import { TutorActivityPanel } from "../features/tutor/TutorActivityPanel";
import { TutorMemoryPanel } from "../features/tutor/TutorMemoryPanel";
import { TutorPlanPreferencesPanel } from "../features/tutor/TutorPlanPreferencesPanel";
import { useTutorSSE } from "../hooks/useTutorSSE";
import { getErrorInfo } from "../lib/errorMessages";
import type {
  ApiError,
  TutorActivityItem,
  TutorInboxItem,
  TutorInputAcceptedResponse,
  TutorMemoryItem,
  TutorPlanRevisionList,
  TutorPreferences,
  TutorRunState,
  TutorSseEvent,
  UserProfile,
} from "../types";

type TutorWorkspacePageProps = {
  user: UserProfile | null;
  /** Child 07 must supply a server-authoritative cutover decision before enabling this surface. */
  enabled?: boolean;
  isActive?: boolean;
  initialConversationId?: string | null;
};

type TutorTimelineEntry = {
  id: string;
  kind: "learner" | "tutor" | "activity" | "notice" | "error";
  text: string;
  detail?: string;
};

type TutorInputAcknowledgement = Pick<
  TutorInputAcceptedResponse,
  "input_revision" | "merged" | "input_replayed" | "idempotent_replayed"
>;

type ControlsStatus = "idle" | "loading" | "ready" | "error";

type PreferenceUpdate = {
  inferredMemoryEnabled?: boolean;
  expectedMemorySettingVersion?: string;
  proactivePaused?: boolean;
};

export function TutorWorkspacePage({
  user,
  enabled = false,
  isActive = true,
  initialConversationId = null,
}: TutorWorkspacePageProps) {
  const [conversationId, setConversationId] = useState<string | null>(initialConversationId);
  const [run, setRun] = useState<TutorRunState | null>(null);
  const [timeline, setTimeline] = useState<TutorTimelineEntry[]>([]);
  const [composerText, setComposerText] = useState("");
  const [composerStatus, setComposerStatus] = useState<"idle" | "submitting">("idle");
  const [composerError, setComposerError] = useState<{ code: string; message: string } | null>(null);
  const [streamError, setStreamError] = useState<ApiError | null>(null);
  const [latestAcknowledgement, setLatestAcknowledgement] = useState<TutorInputAcknowledgement | null>(null);
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
  const activeRunIdRef = useRef<string | null>(null);

  const userId = user?.id ?? null;
  const mayUseTutor = enabled && isActive && userId !== null;
  const isActiveInteractiveRun = Boolean(run && run.origin === "interactive" && run.terminal_outcome === null && !run.cancelled);
  const activeRunId = isActiveInteractiveRun ? run?.run_id ?? null : null;
  activeRunIdRef.current = activeRunId;

  const appendTimeline = useCallback((entry: TutorTimelineEntry) => {
    setTimeline((current) => {
      if (current.some((item) => item.id === entry.id)) {
        return current;
      }
      return [...current, entry].slice(-100);
    });
  }, []);

  const refreshRun = useCallback(async (runId: string) => {
    if (!userId) return;
    try {
      const nextRun = await fetchTutorRun(userId, runId);
      setRun(nextRun);
    } catch (error) {
      const info = getErrorInfo(error);
      setStreamError({
        code: info.code,
        message: info.message,
        details: {},
        request_id: "tutor-workspace",
        recoverable: info.recoverable,
      });
    }
  }, [userId]);

  const loadControls = useCallback(async (signal?: AbortSignal) => {
    if (!userId || !mayUseTutor) {
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
    if (event.type === "input_accepted") {
      setLatestAcknowledgement({
        input_revision: event.data.input_revision,
        merged: true,
        input_replayed: false,
        idempotent_replayed: false,
      });
      appendTimeline({
        id: `tutor-input-${event.id}`,
        kind: "notice",
        text: `已接收第 ${event.data.input_revision} 条输入。`,
        detail: "Tutor 会在下一个安全检查点重新评估学习方向。",
      });
      return;
    }
    if (event.type === "tool_status") {
      appendTimeline({
        id: `tutor-status-${event.id}`,
        kind: "activity",
        text: event.data.message,
        detail: `当前进度：${displayEventStatus(event.data.status)}`,
      });
      return;
    }
    if (event.type === "activity") {
      appendTimeline({
        id: `tutor-activity-${event.id}`,
        kind: "activity",
        text: displayActivityEvent(event.data.category),
        detail: `状态：${displayEventStatus(event.data.status)}`,
      });
      void loadControls();
      return;
    }
    if (event.type === "run_state") {
      void refreshRun(event.data.run_id);
      return;
    }
    if (event.type === "done") {
      appendTimeline({
        id: `tutor-done-${event.id}`,
        kind: "tutor",
        text: event.data.public_message ?? "本次 Tutor 响应已完成。",
      });
      setStreamError(null);
      void refreshRun(event.data.run_id);
      void loadControls();
      return;
    }

    if (event.data.public_message) {
      appendTimeline({
        id: `tutor-error-message-${event.id ?? event.data.error.request_id}`,
        kind: "tutor",
        text: event.data.public_message,
      });
    }
    appendTimeline({
      id: `tutor-error-${event.id ?? event.data.error.request_id}`,
      kind: "error",
      text: event.data.error.message,
      detail: event.data.error.code,
    });
    setStreamError(event.data.error);
    const currentRunId = activeRunIdRef.current;
    if (currentRunId) {
      void refreshRun(currentRunId);
    }
    void loadControls();
  }, [appendTimeline, loadControls, refreshRun]);

  const streamUrl = mayUseTutor && userId && activeRunId ? buildTutorRunEventsUrl(activeRunId, userId) : null;
  const stream = useTutorSSE(streamUrl, {
    enabled: Boolean(streamUrl),
    maxReconnectAttempts: 2,
    onEvent: handleTutorEvent,
    onError: setStreamError,
  });

  useEffect(() => {
    setConversationId(initialConversationId);
    setRun(null);
    setTimeline([]);
    setComposerText("");
    setComposerStatus("idle");
    setComposerError(null);
    setStreamError(null);
    setLatestAcknowledgement(null);
    setActivity([]);
    setInbox([]);
    setMemory([]);
    setPlans(null);
    setPreferences(null);
    setControlsError(null);
    setControlsStatus("idle");
  }, [initialConversationId, mayUseTutor, userId]);

  useEffect(() => {
    if (!mayUseTutor || !userId) return;
    const controller = new AbortController();
    void loadControls(controller.signal);
    return () => controller.abort();
  }, [loadControls, mayUseTutor, userId]);

  async function submitComposer() {
    const content = composerText.trim();
    if (!content || !mayUseTutor || !userId || composerStatus === "submitting") return;

    setComposerStatus("submitting");
    setComposerError(null);
    try {
      let resolvedConversationId = conversationId ?? run?.conversation_id ?? null;
      if (!resolvedConversationId) {
        const conversation = await createTutorConversation({
          userId,
          clientActionId: createTutorActionId("tutor-conversation"),
        });
        resolvedConversationId = conversation.conversation_id;
        setConversationId(resolvedConversationId);
      }

      const clientActionId = createTutorActionId("tutor-input");
      const accepted = isActiveInteractiveRun && run
        ? await acceptTutorRunInput({ userId, runId: run.run_id, content, clientActionId })
        : await acceptTutorConversationInput({ userId, conversationId: resolvedConversationId, content, clientActionId });

      setConversationId(accepted.conversation_id);
      setRun(accepted.run);
      setLatestAcknowledgement({
        input_revision: accepted.input_revision,
        merged: accepted.merged,
        input_replayed: accepted.input_replayed,
        idempotent_replayed: accepted.idempotent_replayed,
      });
      appendTimeline({
        id: `learner-input-${accepted.message_id}`,
        kind: "learner",
        text: content,
      });
      appendTimeline({
        id: `acknowledgement-${accepted.message_id}`,
        kind: "notice",
        text: accepted.merged ? "这条跟进已合并到当前 Tutor 运行。" : "已开始新的 Tutor 学习对话。",
        detail: `输入修订：${accepted.input_revision}`,
      });
      setComposerText("");
    } catch (error) {
      const info = getErrorInfo(error);
      setComposerError({ code: info.code, message: info.message });
      if (info.code === "RUN_NOT_ACTIVE" && run) {
        void refreshRun(run.run_id);
      }
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

  return (
    <main className="tutor-workspace" aria-labelledby="tutor-workspace-title">
      <section className="tutor-main-column">
        <header className="tutor-hero">
          <div>
            <p className="tutor-panel-eyebrow">Tutor 学习对话</p>
            <h1 id="tutor-workspace-title">从你的目标开始</h1>
            <p>用自然语言描述想学什么。Tutor 会根据已确认的学习事实给出下一步；运行中也可以继续补充或改变方向。</p>
          </div>
          <div className="tutor-run-summary" aria-live="polite">
            <span>当前状态</span>
            <strong>{run ? displayRunStatus(run.status, run.terminal_outcome) : "等待你的第一条目标"}</strong>
            {run && <small>已接收 {run.input_revision} 条输入</small>}
            {activeRunId && <small>流游标：{stream.cursor}</small>}
          </div>
        </header>

        {streamError && (
          <div className="tutor-inline-error tutor-stream-error" role="alert">
            <div>
              <strong>{streamError.code}</strong>
              <span>{streamError.message}</span>
            </div>
            {streamError.recoverable && activeRunId && <button className="tutor-text-button" type="button" onClick={stream.retry}>重新连接</button>}
          </div>
        )}
        {composerError && (
          <div className="tutor-inline-error" role="alert">
            <strong>{composerError.code}</strong>
            <span>{composerError.message}</span>
          </div>
        )}
        {latestAcknowledgement && (
          <div className="tutor-acknowledgement" aria-live="polite">
            <strong>{latestAcknowledgement.merged ? "跟进已合并" : "输入已接收"}</strong>
            <span>第 {latestAcknowledgement.input_revision} 条输入已持久化。</span>
            {latestAcknowledgement.input_replayed && <span>这是一次安全重放的确认。</span>}
          </div>
        )}

        <section className="tutor-timeline" aria-label="Tutor 对话时间线">
          {timeline.length === 0 ? (
            <div className="tutor-empty-timeline">
              <strong>可以从一个模糊目标开始</strong>
              <p>例如：理解闭包、准备 JavaScript DOM 项目，或针对某个报错调整学习方向。</p>
            </div>
          ) : (
            timeline.map((item) => (
              <article className={`tutor-timeline-entry ${item.kind}`} key={item.id}>
                <span className="tutor-timeline-label">{timelineLabel(item.kind)}</span>
                <div>
                  <p>{item.text}</p>
                  {item.detail && <small>{item.detail}</small>}
                </div>
              </article>
            ))
          )}
        </section>

        <form className="tutor-composer" onSubmit={(event) => { event.preventDefault(); void submitComposer(); }}>
          <label htmlFor="tutor-composer-input">告诉 Tutor 你想达成什么，或继续补充当前问题</label>
          <textarea
            id="tutor-composer-input"
            value={composerText}
            rows={4}
            maxLength={16_000}
            placeholder="例如：我会写基础 JavaScript，但总弄不清闭包里的变量什么时候会保留。"
            disabled={composerStatus === "submitting"}
            onChange={(event) => setComposerText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                event.preventDefault();
                void submitComposer();
              }
            }}
          />
          <div className="tutor-composer-footer">
            <div className="tutor-goal-examples" aria-label="目标示例">
              {[
                "帮我理清闭包和作用域",
                "我想系统复习 DOM 事件",
                "这个报错我不知道从哪里开始看",
              ].map((example) => (
                <button key={example} type="button" onClick={() => setComposerText(example)} disabled={composerStatus === "submitting"}>{example}</button>
              ))}
            </div>
            <button className="tutor-primary-button" type="submit" disabled={composerStatus === "submitting" || composerText.trim().length === 0}>
              {composerStatus === "submitting" ? "正在确认输入……" : activeRunId ? "发送跟进" : "开始对话"}
            </button>
          </div>
          <p className="tutor-composer-hint">按 Ctrl / ⌘ + Enter 可发送。即使 Tutor 正在处理，也可以继续发送跟进。</p>
        </form>
      </section>

      <aside className="tutor-side-column" aria-label="Tutor 学习控制">
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
      </aside>
    </main>
  );
}

function createTutorActionId(prefix: string): string {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}:${random}`;
}

function displayRunStatus(status: TutorRunState["status"], terminalOutcome: TutorRunState["terminal_outcome"]): string {
  if (terminalOutcome === "completed") return "已完成";
  if (terminalOutcome === "model_unavailable") return "模型暂不可用";
  if (terminalOutcome === "blocked_policy") return "当前操作未获允许";
  if (terminalOutcome === "budget_exhausted") return "本次运行已达到安全限制";
  if (terminalOutcome === "cancelled") return "已停止";
  if (terminalOutcome === "failed") return "未能安全完成";
  return {
    queued: "正在排队",
    leased: "正在准备",
    running: "正在处理",
    waiting_for_input: "等待你的补充",
    waiting_for_capability: "正在等待已允许的能力",
    awaiting_effect_commit: "正在确认学习更新",
    completed: "已完成",
    model_unavailable: "模型暂不可用",
    blocked_policy: "当前操作未获允许",
    budget_exhausted: "本次运行已达到安全限制",
    cancelled: "已停止",
    failed: "未能安全完成",
  }[status];
}

function displayEventStatus(status: string): string {
  if (status === "completed") return "已完成";
  if (status === "running") return "进行中";
  if (status === "accepted") return "已接收";
  if (status === "denied") return "未执行";
  return "已更新";
}

function displayActivityEvent(category: string): string {
  if (category.includes("plan")) return "Tutor 更新了学习计划记录。";
  if (category.includes("memory")) return "Tutor 更新了可检查的学习记录。";
  if (category.includes("runner")) return "Tutor 记录了练习反馈。";
  return "Tutor 记录了一项学习活动。";
}

function timelineLabel(kind: TutorTimelineEntry["kind"]): string {
  return {
    learner: "你",
    tutor: "Tutor",
    activity: "学习动态",
    notice: "已确认",
    error: "需要注意",
  }[kind];
}
