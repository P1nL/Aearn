import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type RefObject } from "react";

import {
  acceptTutorConversationInput, acceptTutorFirstTurn, buildTutorConversationEventsUrl,
  correctTutorMemory, deleteTutorMemory, deleteTutorQueueItem, dismissTutorInbox,
  editTutorQueueItem, executeTutorQueueItem, fetchTutorActivity, fetchTutorConversationSnapshot,
  fetchTutorInbox, fetchTutorMemory, fetchTutorPlanRevisions, fetchTutorPreferences,
  fetchTutorThreadTurnV2Capability, interruptTutorTurn, markTutorInboxRead, reorderTutorQueue,
  respondToTutorInteractionRequest, resumeTutorQueue, retryTutorTurn, rollbackTutorPlan,
  steerTutorQueueItem, updateTutorPreferences,
} from "../../api";
import { useGraphemeTypewriter } from "../../hooks/useGraphemeTypewriter";
import { useTutorConversationStream, type TutorConversationEvent } from "../../hooks/useTutorConversationStream";
import { getErrorInfo } from "../../lib/errorMessages";
import type {
  ExerciseAttemptOutcome, LearningScopeInput, TutorActivityItem, TutorContextReference,
  TutorContextReferenceDraft, TutorHistoryItem, TutorHistoryMessage, TutorInboxItem, TutorInputAcceptedResponse,
  TutorInteractionRequestItem, TutorInteractionResponseDraft, TutorMemoryItem, TutorPlanRevisionList, TutorPreferences,
  TutorPublicTurn, TutorQueuedInput, TutorRuntimeOutput, TutorRuntimeOutputItem,
  TutorThreadTurnV2Capability, TutorTurnOutputPayload, UserProfile,
} from "../../types";
import {
  Button, DisclosureRow, DshDerivedRoot, IconChevronDown, IconChevronUp, IconDelete,
  IconEdit, IconQueue, IconSend, IconStop, Input, StateDot,
} from "../../ui/dsh-derived";
import { TutorActivityPanel } from "./TutorActivityPanel";
import { TutorMemoryPanel } from "./TutorMemoryPanel";
import { TutorPlanPreferencesPanel } from "./TutorPlanPreferencesPanel";

export type TutorComposerReference = { id: string; draft: TutorContextReferenceDraft; label: string };
export type TutorConversationSurfaceProps = {
  user: UserProfile | null; enabled?: boolean; isActive?: boolean;
  selectedConversationId: string | null; onSelectConversation: (conversationId: string | null) => void;
  onConversationsChanged?: () => void; mode?: "general" | "plan_drafting"; showControls?: boolean;
  planningComposerPlaceholder?: string;
  learningScope?: LearningScopeInput; scopeLabel?: string; contextReferences?: TutorComposerReference[];
  onRemoveContextReference?: (referenceId: string) => void;
  onReferencesAccepted?: (references: TutorContextReference[]) => void;
};
type LoadStatus = "idle" | "loading" | "ready" | "error";
type PreferenceUpdate = { inferredMemoryEnabled?: boolean; expectedMemorySettingVersion?: string; proactivePaused?: boolean };
type RequestDraft = string | string[];
type ScrollAnchor = { top: number; height: number };
type TutorLiveThinkingState = {
  turnId: string;
  inputRevision: number;
  generation: number;
  receivedText: string;
  complete: boolean;
  lastChunkSequence: number | null;
  initialText: string;
};
type TutorLiveRuntimeOutputState = TutorRuntimeOutput & { turnId: string };
type TutorRecentCompletion = {
  itemId: string;
  turnId: string;
  initialThinkingText: string;
  streamedThinking: boolean;
};
const PAGE_SIZE = 40;
const TUTOR_TEXT_REVEAL_INTERVAL_MS = 18;
const TUTOR_THINKING_STABILITY_DELAY_MS = 350;
const TUTOR_THINKING_AUTO_COLLAPSE_DELAY_MS = 240;
const GENERAL_EXAMPLES = ["帮我理清闭包和作用域", "我想系统复习 DOM 事件", "这个报错我不知道从哪里开始看"] as const;

export function TutorConversationSurface({
  user, enabled = false, isActive = true, selectedConversationId, onSelectConversation,
  onConversationsChanged, mode = "general", showControls = true, planningComposerPlaceholder, learningScope, scopeLabel,
  contextReferences = [], onRemoveContextReference, onReferencesAccepted,
}: TutorConversationSurfaceProps) {
  const [timeline, setTimeline] = useState<TutorHistoryItem[]>([]);
  const [loadStatus, setLoadStatus] = useState<LoadStatus>("idle");
  const [loadError, setLoadError] = useState<{ code: string; message: string } | null>(null);
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [historyHasMore, setHistoryHasMore] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [streamCursor, setStreamCursor] = useState<string | null>(null);
  const [capability, setCapability] = useState<TutorThreadTurnV2Capability | null>(null);
  const [capabilityStatus, setCapabilityStatus] = useState<LoadStatus>("idle");
  const [activeTurn, setActiveTurn] = useState<TutorPublicTurn | null>(null);
  const [thinkingTurn, setThinkingTurn] = useState<TutorPublicTurn | null>(null);
  const [liveThinking, setLiveThinking] = useState<TutorLiveThinkingState | null>(null);
  const [liveRuntimeOutput, setLiveRuntimeOutput] = useState<TutorLiveRuntimeOutputState | null>(null);
  const [stableThinkingKey, setStableThinkingKey] = useState<string | null>(null);
  const [recentCompletion, setRecentCompletion] = useState<TutorRecentCompletion | null>(null);
  const [controlVersion, setControlVersion] = useState(0);
  const [controlState, setControlState] = useState<"idle" | "running" | "waiting" | "queue_paused">("idle");
  const [queuePaused, setQueuePaused] = useState(false);
  const [queuePauseReason, setQueuePauseReason] = useState<"pending_request" | "interrupted" | "failed" | null>(null);
  const [queue, setQueue] = useState<TutorQueuedInput[]>([]);
  const [maxPending, setMaxPending] = useState(10);
  const [pendingRequest, setPendingRequest] = useState<TutorInteractionRequestItem | null>(null);
  const [composerText, setComposerText] = useState("");
  const [composerStatus, setComposerStatus] = useState<"idle" | "submitting">("idle");
  const [actionError, setActionError] = useState<{ code: string; message: string } | null>(null);
  const [mutationBusy, setMutationBusy] = useState<string | null>(null);
  const [requestDraft, setRequestDraft] = useState<RequestDraft>("");
  const [editingQueueId, setEditingQueueId] = useState<string | null>(null);
  const [queueEditDraft, setQueueEditDraft] = useState("");
  const [controlsStatus, setControlsStatus] = useState<LoadStatus>("idle");
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
  const mayReadTutor = enabled && isActive && userId !== null;
  const writeEnabled = mayReadTutor && capability?.effective_enabled === true;
  const planning = mode === "plan_drafting";
  const selectedRef = useRef(selectedConversationId);
  const requestRef = useRef<AbortController | null>(null);
  const refreshTimerRef = useRef<number | null>(null);
  const timelineRef = useRef<HTMLElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const prependAnchorRef = useRef<ScrollAnchor | null>(null);
  const scrollToLatestRef = useRef(false);
  const activeTurnRef = useRef<TutorPublicTurn | null>(null);
  const liveThinkingRef = useRef<TutorLiveThinkingState | null>(null);
  const liveRuntimeOutputRef = useRef<TutorLiveRuntimeOutputState | null>(null);
  const displayedThinkingRef = useRef("");
  const thinkingRecoveryPendingRef = useRef(false);
  selectedRef.current = selectedConversationId;

  const replaceLiveThinking = useCallback((next: TutorLiveThinkingState | null) => {
    liveThinkingRef.current = next;
    setLiveThinking(next);
  }, []);
  const replaceLiveRuntimeOutput = useCallback((next: TutorLiveRuntimeOutputState | null) => {
    liveRuntimeOutputRef.current = next;
    setLiveRuntimeOutput(next);
  }, []);
  const adoptAcceptedTurn = useCallback((accepted: TutorInputAcceptedResponse) => {
    if (accepted.run.terminal_outcome !== null || accepted.run.cancelled) return;
    const turn: TutorPublicTurn = {
      turn_id: accepted.run_id,
      conversation_id: accepted.conversation_id,
      interaction_protocol_version: accepted.run.interaction_protocol_version,
      status: "in_progress",
      input_revision: accepted.input_revision,
      retry_of_turn_id: accepted.run.retry_of_turn_id,
      retry_root_turn_id: accepted.run.retry_root_turn_id,
      completion_reason: accepted.run.completion_reason,
      created_at: accepted.run.created_at,
      updated_at: accepted.run.updated_at,
    };
    activeTurnRef.current = turn;
    setActiveTurn(turn);
    setThinkingTurn(turn);
    replaceLiveThinking(null);
    replaceLiveRuntimeOutput(null);
    setControlState("running");
    setPendingRequest(null);
    scrollToLatestRef.current = true;
  }, [replaceLiveRuntimeOutput, replaceLiveThinking]);
  const liveThinkingKey = liveThinking ? `${liveThinking.turnId}:${liveThinking.inputRevision}:${liveThinking.generation}` : null;
  const hasBufferedThinkingText = Boolean(liveThinking?.receivedText);
  const restoredThinkingText = Boolean(liveThinking?.initialText && liveThinking.complete);
  useEffect(() => {
    if (!liveThinkingKey || !hasBufferedThinkingText || restoredThinkingText) {
      setStableThinkingKey(null);
      return;
    }
    const timer = window.setTimeout(() => setStableThinkingKey(liveThinkingKey), TUTOR_THINKING_STABILITY_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [hasBufferedThinkingText, liveThinkingKey, restoredThinkingText]);
  const revealLiveThinking = restoredThinkingText || Boolean(liveThinking?.complete && stableThinkingKey === liveThinkingKey);
  const liveThinkingTargetText = revealLiveThinking ? liveThinking?.receivedText ?? "" : "";
  const liveThinkingTypewriter = useGraphemeTypewriter(liveThinkingTargetText, {
    animate: revealLiveThinking,
    initialText: revealLiveThinking ? liveThinking?.initialText ?? "" : "",
    resetKey: liveThinkingKey ?? "none",
    intervalMs: TUTOR_TEXT_REVEAL_INTERVAL_MS,
  });
  displayedThinkingRef.current = liveThinkingTypewriter.text;

  const applySnapshot = useCallback((snapshot: Awaited<ReturnType<typeof fetchTutorConversationSnapshot>>, placement: "replace" | "prepend") => {
    const visible = reconcileVisibleTimeline(snapshot.timeline.filter((item) => item.kind !== "process").reverse());
    let preserveThinkingHandoff = false;
    if (placement === "replace") {
      const previousTurn = activeTurnRef.current;
      if (previousTurn && snapshot.active_turn?.turn_id !== previousTurn.turn_id) {
        const completedItem = visible.find((item) =>
          ((item.kind === "message" && item.role === "tutor") || item.kind === "elicitation" || item.kind === "approval") &&
          item.turn_id === previousTurn.turn_id,
        );
        const terminalError = visible.find((item) => item.kind === "error" && item.turn_id === previousTurn.turn_id);
        if (completedItem) {
          const previousLive = liveThinkingRef.current;
          setRecentCompletion({
            itemId: completedItem.id,
            turnId: previousTurn.turn_id,
            initialThinkingText: displayedThinkingRef.current,
            streamedThinking: Boolean(previousLive?.receivedText),
          });
        } else if (!terminalError && !snapshot.active_turn && liveThinkingRef.current?.turnId === previousTurn.turn_id && liveThinkingRef.current.receivedText) {
          preserveThinkingHandoff = true;
          setThinkingTurn(previousTurn);
        } else {
          setRecentCompletion(null);
        }
      }
    }
    setTimeline((current) => reconcileVisibleTimeline(placement === "prepend" ? [...visible, ...current] : visible));
    if (!preserveThinkingHandoff) {
      activeTurnRef.current = snapshot.active_turn;
      setThinkingTurn(snapshot.active_turn);
    }
    setActiveTurn(snapshot.active_turn);

    if (placement === "replace") {
      const incomingTurn = snapshot.active_turn;
      const incomingThinking = snapshot.active_thinking;
      const current = liveThinkingRef.current;
      const recoveringThinking = thinkingRecoveryPendingRef.current;
      if (!incomingTurn) {
        if (!preserveThinkingHandoff) replaceLiveThinking(null);
      } else if (incomingThinking && incomingThinking.turn_id === incomingTurn.turn_id && incomingThinking.input_revision === incomingTurn.input_revision) {
        const sameTurnRevision = current && current.turnId === incomingThinking.turn_id &&
          current.inputRevision === incomingThinking.input_revision;
        if (!sameTurnRevision || incomingThinking.generation >= current.generation) {
          const sameGeneration = sameTurnRevision && current.generation === incomingThinking.generation;
          let receivedText = incomingThinking.text;
          let initialText = incomingThinking.text;
          let complete = incomingThinking.complete;
          let lastChunkSequence: number | null = null;
          if (sameGeneration) {
            if (incomingThinking.text.startsWith(current.receivedText)) receivedText = incomingThinking.text;
            else if (current.receivedText.startsWith(incomingThinking.text)) receivedText = current.receivedText;
            initialText = current.initialText;
            complete = current.complete || incomingThinking.complete;
            lastChunkSequence = current.lastChunkSequence;
          }
          replaceLiveThinking({
            turnId: incomingThinking.turn_id,
            inputRevision: incomingThinking.input_revision,
            generation: incomingThinking.generation,
            receivedText,
            complete,
            lastChunkSequence,
            initialText,
          });
        }
      } else if (recoveringThinking || !current || current.turnId !== incomingTurn.turn_id || current.inputRevision !== incomingTurn.input_revision) {
        replaceLiveThinking(null);
      }
      thinkingRecoveryPendingRef.current = false;
      const incomingRuntime = snapshot.active_runtime_output;
      const currentRuntime = liveRuntimeOutputRef.current;
      if (!incomingTurn) {
        replaceLiveRuntimeOutput(null);
      } else if (!incomingRuntime) {
        if (currentRuntime && (currentRuntime.turnId !== incomingTurn.turn_id ||
            currentRuntime.input_revision !== incomingTurn.input_revision)) {
          replaceLiveRuntimeOutput(null);
        }
      } else {
        const nextRuntime: TutorLiveRuntimeOutputState = {
          ...incomingRuntime,
          turnId: incomingTurn.turn_id,
        };
        if (currentRuntime && currentRuntime.turnId === incomingTurn.turn_id &&
            currentRuntime.input_revision === incomingRuntime.input_revision &&
            currentRuntime.generation === incomingRuntime.generation) {
          replaceLiveRuntimeOutput(mergeRuntimeOutputs(currentRuntime, nextRuntime));
        } else if (!currentRuntime || incomingRuntime.generation >= currentRuntime.generation) {
          replaceLiveRuntimeOutput(nextRuntime);
        }
      }
    }

    setControlVersion(snapshot.conversation.control_version);
    setControlState(snapshot.conversation.control_state);
    setQueuePaused(snapshot.conversation.queue_paused);
    setQueuePauseReason(snapshot.conversation.queue_pause_reason);
    setQueue(snapshot.queue);
    setMaxPending(snapshot.conversation.max_pending);
    setPendingRequest(snapshot.pending_requests.find((request) => request.state === "pending") ?? null);
    setStreamCursor(snapshot.stream_cursor);
    if (placement === "replace") {
      setHistoryCursor(snapshot.next_cursor); setHistoryHasMore(snapshot.has_more);
      setLoadStatus("ready"); setLoadError(null); scrollToLatestRef.current = true;
    }
  }, [replaceLiveRuntimeOutput, replaceLiveThinking]);

  const loadSnapshot = useCallback(async (conversationId: string, options: { cursor?: string | null; placement?: "replace" | "prepend"; showLoading?: boolean } = {}) => {
    if (!mayReadTutor || !userId || selectedRef.current !== conversationId) return null;
    requestRef.current?.abort();
    const controller = new AbortController(); requestRef.current = controller;
    const placement = options.placement ?? "replace";
    if (options.showLoading) { setLoadStatus("loading"); setLoadError(null); if (placement === "replace") setTimeline([]); }
    try {
      const snapshot = await fetchTutorConversationSnapshot({ userId, conversationId, limit: PAGE_SIZE, cursor: options.cursor, signal: controller.signal });
      if (controller.signal.aborted || selectedRef.current !== conversationId) return null;
      applySnapshot(snapshot, placement); return snapshot;
    } catch (error) {
      if (controller.signal.aborted) return null;
      const info = getErrorInfo(error); setLoadError({ code: info.code, message: info.message }); setLoadStatus("error"); return null;
    } finally { if (requestRef.current === controller) requestRef.current = null; }
  }, [applySnapshot, mayReadTutor, userId]);

  const refreshSnapshot = useCallback(() => { const id = selectedRef.current; if (id) void loadSnapshot(id); }, [loadSnapshot]);
  const scheduleRefresh = useCallback(() => {
    if (refreshTimerRef.current !== null) return;
    refreshTimerRef.current = window.setTimeout(() => { refreshTimerRef.current = null; refreshSnapshot(); }, 80);
  }, [refreshSnapshot]);

  const requireThinkingSnapshot = useCallback(() => {
    thinkingRecoveryPendingRef.current = true;
    refreshSnapshot();
  }, [refreshSnapshot]);

  const consumeRuntimeOutput = useCallback((
    event: Extract<TutorConversationEvent, { kind: "turn_output" }>,
  ) => {
    const turn = activeTurnRef.current;
    const { payload } = event;
    if (payload.output_version !== "tutor_runtime_item_stream_v1") return false;
    if (!turn || !event.turn_id || event.turn_id !== turn.turn_id ||
        payload.input_revision !== turn.input_revision) {
      requireThinkingSnapshot();
      return true;
    }
    const reduced = reduceRuntimeOutput(
      liveRuntimeOutputRef.current,
      turn.turn_id,
      payload,
    );
    if (reduced === undefined) {
      requireThinkingSnapshot();
      return true;
    }
    replaceLiveRuntimeOutput(reduced);
    return true;
  }, [replaceLiveRuntimeOutput, requireThinkingSnapshot]);

  const consumeTurnOutput = useCallback((event: Extract<TutorConversationEvent, { kind: "turn_output" }>) => {
    if (consumeRuntimeOutput(event)) return;
    const turn = activeTurnRef.current;
    const { payload } = event;
    if (!turn || !event.turn_id || event.turn_id !== turn.turn_id || payload.input_revision !== turn.input_revision) {
      requireThinkingSnapshot();
      return;
    }
    const current = liveThinkingRef.current;
    if (payload.operation === "reset") {
      if (payload.chunk_sequence !== 0) {
        requireThinkingSnapshot();
        return;
      }
      thinkingRecoveryPendingRef.current = false;
      replaceLiveThinking({
        turnId: turn.turn_id,
        inputRevision: payload.input_revision,
        generation: payload.generation,
        receivedText: "",
        complete: false,
        lastChunkSequence: 0,
        initialText: "",
      });
      return;
    }
    if (!current) {
      if (payload.operation !== "append" || payload.chunk_sequence !== 1) {
        requireThinkingSnapshot();
        return;
      }
      thinkingRecoveryPendingRef.current = false;
      replaceLiveThinking({
        turnId: turn.turn_id,
        inputRevision: payload.input_revision,
        generation: payload.generation,
        receivedText: payload.text,
        complete: false,
        lastChunkSequence: payload.chunk_sequence,
        initialText: "",
      });
      return;
    }
    if (current.turnId !== turn.turn_id || current.inputRevision !== payload.input_revision || current.generation !== payload.generation) {
      requireThinkingSnapshot();
      return;
    }
    if (current.lastChunkSequence !== null) {
      if (payload.chunk_sequence <= current.lastChunkSequence) return;
      if (payload.chunk_sequence !== current.lastChunkSequence + 1) {
        requireThinkingSnapshot();
        return;
      }
    }
    if (payload.operation === "discard") {
      thinkingRecoveryPendingRef.current = false;
      replaceLiveThinking(null);
      return;
    }
    if (payload.operation === "complete") {
      thinkingRecoveryPendingRef.current = false;
      replaceLiveThinking({ ...current, complete: true, lastChunkSequence: payload.chunk_sequence });
      return;
    }
    if (payload.operation !== "append") {
      requireThinkingSnapshot();
      return;
    }
    const receivedText = current.receivedText + payload.text;
    if (receivedText.length > 1280) {
      requireThinkingSnapshot();
      return;
    }
    thinkingRecoveryPendingRef.current = false;
    replaceLiveThinking({ ...current, receivedText, lastChunkSequence: payload.chunk_sequence });
  }, [consumeRuntimeOutput, replaceLiveThinking, requireThinkingSnapshot]);

  const loadCapability = useCallback(async (signal?: AbortSignal) => {
    if (!mayReadTutor || !userId) { setCapability(null); setCapabilityStatus("idle"); return; }
    setCapabilityStatus("loading");
    try { setCapability(await fetchTutorThreadTurnV2Capability(userId, signal)); if (!signal?.aborted) setCapabilityStatus("ready"); }
    catch { if (!signal?.aborted) { setCapability(null); setCapabilityStatus("error"); } }
  }, [mayReadTutor, userId]);

  const loadControls = useCallback(async (signal?: AbortSignal) => {
    if (!userId || !mayReadTutor || !showControls) { setControlsStatus("idle"); return; }
    setControlsStatus("loading"); setControlsError(null);
    try {
      const [a, i, m, p, prefs] = await Promise.all([fetchTutorActivity(userId, signal), fetchTutorInbox(userId, signal), fetchTutorMemory(userId, signal), fetchTutorPlanRevisions(userId, signal), fetchTutorPreferences(userId, signal)]);
      if (signal?.aborted) return;
      setActivity(a); setInbox(i); setMemory(m); setPlans(p); setPreferences(prefs); setControlsStatus("ready");
    } catch (error) { if (!signal?.aborted) { setControlsError(getErrorInfo(error).message); setControlsStatus("error"); } }
  }, [mayReadTutor, showControls, userId]);


  const streamUrl = mayReadTutor && userId && selectedConversationId ? buildTutorConversationEventsUrl(selectedConversationId, userId) : null;
  const stream = useTutorConversationStream(streamUrl, {
    enabled: Boolean(streamUrl && streamCursor), initialCursor: streamCursor, maxReconnectAttempts: 3,
    onEvent: (event) => {
      if (event.kind === "turn_output") consumeTurnOutput(event);
      else { scheduleRefresh(); onConversationsChanged?.(); }
    },
    onResetRequired: requireThinkingSnapshot,
  });

  useEffect(() => { const controller = new AbortController(); void loadCapability(controller.signal); return () => controller.abort(); }, [loadCapability]);
  useEffect(() => {
    requestRef.current?.abort();
    if (refreshTimerRef.current !== null) window.clearTimeout(refreshTimerRef.current);
    setComposerText(""); setActionError(null); setEditingQueueId(null); setRequestDraft("");
    setRecentCompletion(null); setStableThinkingKey(null); replaceLiveThinking(null); replaceLiveRuntimeOutput(null); displayedThinkingRef.current = "";
    thinkingRecoveryPendingRef.current = false;
    activeTurnRef.current = null; setActiveTurn(null); setThinkingTurn(null);
    if (!mayReadTutor || !selectedConversationId) {
      setTimeline([]); setLoadStatus("idle"); setLoadError(null);
      setQueue([]); setPendingRequest(null); setStreamCursor(null); return;
    }
    void loadSnapshot(selectedConversationId, { placement: "replace", showLoading: true });
  }, [loadSnapshot, mayReadTutor, replaceLiveRuntimeOutput, replaceLiveThinking, selectedConversationId]);
  useEffect(() => { if (!mayReadTutor || !userId) return; const controller = new AbortController(); void loadControls(controller.signal); return () => controller.abort(); }, [loadControls, mayReadTutor, userId]);
  useEffect(() => { setRequestDraft(initialRequestDraft(pendingRequest)); }, [pendingRequest?.id, pendingRequest?.version]);
  useEffect(() => () => { requestRef.current?.abort(); if (refreshTimerRef.current !== null) window.clearTimeout(refreshTimerRef.current); }, []);
  useEffect(() => {
    const element = timelineRef.current; if (!element) return;
    if (prependAnchorRef.current) { const anchor = prependAnchorRef.current; element.scrollTop = anchor.top + element.scrollHeight - anchor.height; prependAnchorRef.current = null; }
    else if (scrollToLatestRef.current) { element.scrollTop = element.scrollHeight; scrollToLatestRef.current = false; }
  }, [activeTurn?.turn_id, timeline]);

  async function loadOlder() {
    if (!selectedConversationId || !historyCursor || loadingOlder) return;
    const element = timelineRef.current; if (element) prependAnchorRef.current = { top: element.scrollTop, height: element.scrollHeight };
    setLoadingOlder(true);
    try { const snapshot = await loadSnapshot(selectedConversationId, { cursor: historyCursor, placement: "prepend" }); if (snapshot) { setHistoryCursor(snapshot.next_cursor); setHistoryHasMore(snapshot.has_more); } }
    finally { setLoadingOlder(false); }
  }

  async function runMutation(key: string, operation: () => Promise<unknown>) {
    if (!writeEnabled || mutationBusy) return;
    setMutationBusy(key); setActionError(null);
    try { await operation(); onConversationsChanged?.(); refreshSnapshot(); }
    catch (error) { const info = getErrorInfo(error); setActionError({ code: info.code, message: info.message }); refreshSnapshot(); }
    finally { setMutationBusy(null); }
  }

  async function submitComposer() {
    const content = composerText.trim();
    if (!content || !writeEnabled || !userId || composerStatus === "submitting" || pendingRequest) return;
    setComposerStatus("submitting"); setActionError(null);
    try {
      const accepted = selectedConversationId
        ? await acceptTutorConversationInput({
            userId, conversationId: selectedConversationId, content,
            clientActionId: createTutorActionId("tutor-conversation-input"),
            ...(learningScope ? { learningScope } : planning ? { learningScope: { scope_kind: "plan_drafting" as const, task_kind: "plan_drafting" as const } } : {}),
            ...(contextReferences.length ? { contextReferences: contextReferences.map((item) => item.draft) } : {}),
          })
        : await acceptTutorFirstTurn({ userId, content, clientActionId: createTutorActionId("tutor-first-turn"), ...(learningScope ? { learningScope } : {}), ...(contextReferences.length ? { contextReferences: contextReferences.map((item) => item.draft) } : {}) });
      setComposerText("");
      if (!("queued" in accepted)) adoptAcceptedTurn(accepted);
      if (!("queued" in accepted) && contextReferences.length === accepted.context_references.length) onReferencesAccepted?.(accepted.context_references);
      onConversationsChanged?.();
      if (selectedConversationId !== accepted.conversation_id) onSelectConversation(accepted.conversation_id); else refreshSnapshot();
    } catch (error) { const info = getErrorInfo(error); setActionError({ code: info.code, message: info.message }); refreshSnapshot(); }
    finally { setComposerStatus("idle"); }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); void submitComposer(); } }
  function respondToPendingRequest(response: TutorInteractionResponseDraft) {
    if (!userId || !selectedConversationId || !pendingRequest) return;
    void runMutation(`request:${pendingRequest.id}`, async () => {
      const accepted = await respondToTutorInteractionRequest({ userId, conversationId: selectedConversationId, itemId: pendingRequest.id, expectedRequestVersion: pendingRequest.version, response, clientActionId: createTutorActionId("tutor-request-response") });
      adoptAcceptedTurn(accepted);
      return accepted;
    });
  }
  function submitRequestDraft() {
    if (!pendingRequest || pendingRequest.kind === "approval" || pendingRequest.actor !== "learner") return;
    if (pendingRequest.request_kind === "clarification") { const answer = typeof requestDraft === "string" ? requestDraft.trim() : ""; if (answer) respondToPendingRequest({ kind: "clarification", answer_text: answer }); return; }
    if (pendingRequest.request_kind !== "planning_input") return;
    const key = planningQuestionKey(presentationFieldKey(pendingRequest.presentation)); if (!key) return;
    const value = pendingRequest.presentation.type === "integer" ? Number(requestDraft) : requestDraft;
    respondToPendingRequest({ kind: "planning_input", question_key: key, catalog_version: "tutor_planning_questions_v1", value });
  }
  function reorder(itemId: string, direction: -1 | 1) {
    if (!userId || !selectedConversationId) return;
    const index = queue.findIndex((item) => item.item_id === itemId); const target = index + direction;
    if (index < 0 || target < 0 || target >= queue.length) return;
    const itemIds = queue.map((item) => item.item_id); [itemIds[index], itemIds[target]] = [itemIds[target], itemIds[index]];
    void runMutation(`reorder:${itemId}`, () => reorderTutorQueue({ userId, conversationId: selectedConversationId, itemIds, expectedControlVersion: controlVersion, clientActionId: createTutorActionId("tutor-queue-reorder") }));
  }
  function saveQueueEdit(item: TutorQueuedInput) {
    const content = queueEditDraft.trim(); if (!userId || !selectedConversationId || !content) return;
    void runMutation(`edit:${item.item_id}`, async () => { await editTutorQueueItem({ userId, conversationId: selectedConversationId, itemId: item.item_id, content, expectedControlVersion: controlVersion, expectedItemVersion: item.version, clientActionId: createTutorActionId("tutor-queue-edit") }); setEditingQueueId(null); });
  }

  async function handleMarkInboxRead(id: string) { if (!userId || !writeEnabled) return; setBusyInboxId(id); try { const item = await markTutorInboxRead({ userId, inboxId: id, clientActionId: createTutorActionId("tutor-inbox-read") }); setInbox((current) => current.map((entry) => entry.inbox_id === item.inbox_id ? item : entry)); } finally { setBusyInboxId(null); } }
  async function handleDismissInbox(id: string) { if (!userId || !writeEnabled) return; setBusyInboxId(id); try { const item = await dismissTutorInbox({ userId, inboxId: id, clientActionId: createTutorActionId("tutor-inbox-dismiss") }); setInbox((current) => current.filter((entry) => entry.inbox_id !== item.inbox_id)); } finally { setBusyInboxId(null); } }
  async function handleCorrectMemory(id: string, statement: string) { if (!userId || !writeEnabled) return; setBusyMemoryId(id); try { const corrected = await correctTutorMemory({ userId, entryId: id, statement, clientActionId: createTutorActionId("tutor-memory-correct") }); setMemory((current) => [...current.filter((entry) => entry.entry_id !== id), corrected]); } finally { setBusyMemoryId(null); } }
  async function handleDeleteMemory(id: string) { if (!userId || !writeEnabled) return; setBusyMemoryId(id); try { await deleteTutorMemory({ userId, entryId: id, clientActionId: createTutorActionId("tutor-memory-delete") }); setMemory((current) => current.filter((entry) => entry.entry_id !== id)); } finally { setBusyMemoryId(null); } }
  async function handleRollbackPlan() { if (!userId || !writeEnabled) return; setPendingPlanOrPreferenceAction("rollback"); try { await rollbackTutorPlan({ userId, clientActionId: createTutorActionId("tutor-plan-rollback") }); await loadControls(); } finally { setPendingPlanOrPreferenceAction(null); } }
  async function handleUpdatePreferences(update: PreferenceUpdate) { if (!userId || !writeEnabled) return; setPendingPlanOrPreferenceAction(update.proactivePaused === undefined ? "memory" : "proactive"); try { setPreferences(await updateTutorPreferences({ userId, clientActionId: createTutorActionId("tutor-preferences"), ...update })); } finally { setPendingPlanOrPreferenceAction(null); } }

  if (!user) return <Boundary eyebrow="Tutor 工作台" title="先选择学习者">完成本地学习者建档后，才能加载个人的 Tutor 对话与学习记录。</Boundary>;
  if (!enabled) return <Boundary eyebrow="Tutor 工作台" title="Tutor 工作台不可用">当前入口尚未启用，Desktop 不会绕过服务端能力边界。</Boundary>;

  const planningIdle = planning && loadStatus === "ready" && timeline.length === 0 && !activeTurn && !loadError;
  const workspaceClassName = showControls ? "tutor-workspace" : `tutor-workspace tutor-conversation-only${planningIdle ? " tutor-conversation-idle" : ""}`;
  const mutationsLocked = !writeEnabled || Boolean(pendingRequest) || Boolean(mutationBusy);
  const running = activeTurn?.status === "in_progress" && controlState === "running";
  const sendLabel = composerStatus === "submitting" ? "正在确认……" : running ? "加入 Queue" : selectedConversationId ? "发送消息" : "开始对话";


  return <DshDerivedRoot className="tutor-surface-root"><main className={workspaceClassName} aria-label={planning ? "学习计划对话" : undefined} aria-labelledby={planning ? undefined : "tutor-workspace-title"}>
    <section className="tutor-main-column">
      {!planning && <header className="tutor-hero"><div><p className="tutor-panel-eyebrow">Tutor 学习对话</p><h1 id="tutor-workspace-title">{selectedConversationId ? "当前学习对话" : "新对话"}</h1><p>快照是可见状态权威来源；对话事件流只负责触发增量恢复。</p></div><div className="tutor-run-summary" aria-live="polite"><span>当前状态</span><strong>{displayControlState(controlState, activeTurn)}</strong>{streamUrl && <small>对话流：{displayStreamStatus(stream.status)}</small>}</div></header>}
      {scopeLabel ? <div className="tutor-learning-scope" role="status"><span>当前学习范围</span><strong>{scopeLabel}</strong></div> : null}
      {capabilityStatus === "loading" && <div className="tutor-read-only-notice" role="status">正在核对全局 thread/turn v2 能力……</div>}
      {capabilityStatus !== "loading" && !writeEnabled && <div className="tutor-read-only-notice" role="alert"><div><strong>只读模式</strong><span>全局 thread/turn v2 能力未生效；Desktop 不会使用旧 run-local 写入路径。</span></div><Button size="sm" variant="outline" onClick={() => void loadCapability()}>重新核对</Button></div>}
      {stream.error && <div className="tutor-inline-error tutor-stream-error" role="alert"><div><strong>{stream.error.code}</strong><span>{stream.error.message}</span></div><Button size="sm" variant="outline" onClick={stream.retry}>重新连接</Button></div>}
      {actionError && <div className="tutor-inline-error" role="alert"><strong>{actionError.code}</strong><span>{actionError.message}</span></div>}

      <section className={`tutor-timeline${planning ? " tutor-chatgpt-timeline" : ""}`} ref={timelineRef} aria-label="Tutor 对话时间线" aria-busy={loadStatus === "loading"}>
        {historyHasMore && <button className="tutor-load-earlier" type="button" onClick={() => void loadOlder()} disabled={loadingOlder}>{loadingOlder ? "正在加载更早记录……" : "加载更早记录"}</button>}
        {loadStatus === "loading" && timeline.length === 0 && <div className="tutor-empty-timeline"><strong>正在恢复权威对话快照……</strong></div>}
        {loadStatus === "error" && loadError && <div className="tutor-inline-error" role="alert"><div><strong>{loadError.code}</strong><span>{loadError.message}</span></div><Button size="sm" variant="outline" onClick={refreshSnapshot}>重试</Button></div>}
        {loadStatus !== "loading" && timeline.length === 0 && !loadError && !planning && !thinkingTurn && <div className="tutor-empty-timeline"><strong>{selectedConversationId ? "这里还没有可见记录" : "可以从一个模糊目标开始"}</strong></div>}
        {timeline.map((item) => <TimelineItem key={`${item.kind}:${item.id}`} item={item} recentCompletion={recentCompletion} writeEnabled={writeEnabled} mutationBusy={mutationBusy} onRetry={(turnId) => { if (!userId || !selectedConversationId) return; void runMutation(`retry:${turnId}`, () => retryTutorTurn({ userId, conversationId: selectedConversationId, turnId, expectedControlVersion: controlVersion, clientActionId: createTutorActionId("tutor-turn-retry") })); }} />)}
        {thinkingTurn && (running || Boolean(liveThinking?.receivedText) || runtimeOutputHasContent(liveRuntimeOutput)) ? <TutorRunningPlaceholder
          key={`${thinkingTurn.turn_id}:${liveRuntimeOutput?.generation ?? liveThinking?.generation ?? "pending"}`}
          turn={thinkingTurn}
          hasText={Boolean(liveThinkingTargetText)}
          text={liveThinkingTypewriter.text}
          complete={Boolean(liveThinking?.complete && liveThinkingTypewriter.complete)}
          runtimeOutput={liveRuntimeOutput}
        /> : null}
      </section>

      {pendingRequest ? <TypedRequestSeat request={pendingRequest} draft={requestDraft} busy={mutationBusy === `request:${pendingRequest.id}`} disabled={!writeEnabled} onDraftChange={setRequestDraft} onSubmit={submitRequestDraft} onApprove={(decision) => respondToPendingRequest({ kind: "approval", proposal_identity: pendingRequest.kind === "approval" ? pendingRequest.presentation.proposal_id : "", decision })} /> : <>
        {selectedConversationId && queue.length > 0 && <QueueTray
          items={queue} maxPending={maxPending} activeTurn={activeTurn} paused={queuePaused} pauseReason={queuePauseReason}
          disabled={mutationsLocked} busyKey={mutationBusy} editingId={editingQueueId} editDraft={queueEditDraft}
          onBeginEdit={(item) => { setEditingQueueId(item.item_id); setQueueEditDraft(item.content); }} onCancelEdit={() => setEditingQueueId(null)} onEditDraft={setQueueEditDraft} onSaveEdit={saveQueueEdit} onMove={reorder}
          onDelete={(item) => { if (!userId || !selectedConversationId) return; void runMutation(`delete:${item.item_id}`, () => deleteTutorQueueItem({ userId, conversationId: selectedConversationId, itemId: item.item_id, expectedControlVersion: controlVersion, expectedItemVersion: item.version, clientActionId: createTutorActionId("tutor-queue-delete") })); }}
          onSteer={(item) => { if (!userId || !selectedConversationId || !activeTurn) return; void runMutation(`steer:${item.item_id}`, () => steerTutorQueueItem({ userId, conversationId: selectedConversationId, itemId: item.item_id, expectedTurnId: activeTurn.turn_id, expectedInputRevision: activeTurn.input_revision, expectedControlVersion: controlVersion, clientActionId: createTutorActionId("tutor-queue-steer") })); }}
          onExecute={(item) => { if (!userId || !selectedConversationId) return; void runMutation(`execute:${item.item_id}`, () => executeTutorQueueItem({ userId, conversationId: selectedConversationId, itemId: item.item_id, expectedControlVersion: controlVersion, clientActionId: createTutorActionId("tutor-queue-execute") })); }}
          onResume={() => { if (!userId || !selectedConversationId) return; void runMutation("resume", () => resumeTutorQueue({ userId, conversationId: selectedConversationId, expectedControlVersion: controlVersion, clientActionId: createTutorActionId("tutor-queue-resume") })); }}
        />}
        {running && selectedConversationId && activeTurn && <div className="tutor-running-controls" role="status"><span>当前 Turn 正在运行；发送新消息会进入 Queue。</span><Button variant="outline" size="sm" icon={<IconStop />} busy={mutationBusy === "interrupt"} disabled={!writeEnabled || Boolean(mutationBusy)} onClick={() => { if (!userId) return; void runMutation("interrupt", () => interruptTutorTurn({ userId, conversationId: selectedConversationId, expectedTurnId: activeTurn.turn_id, expectedInputRevision: activeTurn.input_revision, expectedControlVersion: controlVersion, clientActionId: createTutorActionId("tutor-turn-interrupt") })); }}>停止</Button></div>}
        <Composer planning={planning} planningIdle={planningIdle} planningPlaceholder={planningComposerPlaceholder} selectedConversationId={selectedConversationId} text={composerText} status={composerStatus} disabled={!writeEnabled} sendLabel={sendLabel} contextReferences={contextReferences} composerRef={composerRef} onTextChange={setComposerText} onKeyDown={handleComposerKeyDown} onSubmit={() => void submitComposer()} onRemoveReference={onRemoveContextReference} />
      </>}
    </section>

    {showControls && writeEnabled && <aside className="tutor-side-column" aria-label="Tutor 学习控制">
      <TutorActivityPanel activity={activity} inbox={inbox} loading={controlsStatus === "loading"} errorMessage={controlsStatus === "error" ? controlsError : null} busyInboxId={busyInboxId} onRetry={() => void loadControls()} onMarkRead={handleMarkInboxRead} onDismiss={handleDismissInbox} />
      <TutorMemoryPanel memory={memory} loading={controlsStatus === "loading"} errorMessage={controlsStatus === "error" ? controlsError : null} busyEntryId={busyMemoryId} onRetry={() => void loadControls()} onCorrect={handleCorrectMemory} onDelete={handleDeleteMemory} />
      <TutorPlanPreferencesPanel plans={plans} preferences={preferences} loading={controlsStatus === "loading"} errorMessage={controlsStatus === "error" ? controlsError : null} pendingAction={pendingPlanOrPreferenceAction} onRetry={() => void loadControls()} onRollback={handleRollbackPlan} onUpdatePreferences={handleUpdatePreferences} />
    </aside>}
  </main></DshDerivedRoot>;
}

function Boundary({ eyebrow, title, children }: { eyebrow: string; title: string; children: string }) { return <section className="tutor-workspace tutor-workspace-boundary" aria-labelledby="tutor-workspace-title"><p className="tutor-panel-eyebrow">{eyebrow}</p><h1 id="tutor-workspace-title">{title}</h1><p>{children}</p></section>; }

function Composer({ planning, planningIdle, planningPlaceholder, selectedConversationId, text, status, disabled, sendLabel, contextReferences, composerRef, onTextChange, onKeyDown, onSubmit, onRemoveReference }: {
  planning: boolean; planningIdle: boolean; planningPlaceholder?: string; selectedConversationId: string | null; text: string; status: "idle" | "submitting"; disabled: boolean; sendLabel: string;
  contextReferences: TutorComposerReference[]; composerRef: RefObject<HTMLTextAreaElement | null>;
  onTextChange: (value: string) => void; onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void; onSubmit: () => void; onRemoveReference?: (id: string) => void;
}) {
  const form = <form className={`tutor-composer${planning ? " tutor-composer-chatgpt" : ""}`} onSubmit={(event) => { event.preventDefault(); onSubmit(); }}>
    <label className={planning ? "visually-hidden" : undefined} htmlFor="tutor-composer-input">{planning ? "告诉 Tutor 你的目标或调整意见" : selectedConversationId ? "继续当前对话" : "从你的学习目标开始"}</label>
    {contextReferences.length > 0 ? <TutorReferenceDraftChips references={contextReferences} disabled={status === "submitting" || disabled} onRemove={onRemoveReference} /> : null}
    {planning ? <div className="tutor-composer-chatgpt-shell"><textarea ref={composerRef} id="tutor-composer-input" value={text} rows={2} maxLength={16_000} placeholder={planningPlaceholder ?? "描述你想学习什么"} disabled={disabled || status === "submitting"} onChange={(event) => onTextChange(event.target.value)} onKeyDown={onKeyDown} /><button className="tutor-composer-send" type="submit" aria-label={sendLabel} title={sendLabel} disabled={disabled || status === "submitting" || !text.trim()}><IconSend /></button></div> : <><textarea ref={composerRef} id="tutor-composer-input" value={text} rows={4} maxLength={16_000} placeholder="例如：我会写基础 JavaScript，但总弄不清闭包里的变量什么时候会保留。" disabled={disabled || status === "submitting"} onChange={(event) => onTextChange(event.target.value)} onKeyDown={onKeyDown} /><div className="tutor-composer-footer"><div className="tutor-goal-examples" aria-label="目标示例">{GENERAL_EXAMPLES.map((example) => <button key={example} type="button" onClick={() => onTextChange(example)} disabled={disabled || status === "submitting"}>{example}</button>)}</div><Button variant="primary" type="submit" busy={status === "submitting"} disabled={disabled || !text.trim()} icon={<IconSend />}>{sendLabel}</Button></div></>}
    {!planningIdle && <p className="tutor-composer-hint">按 Ctrl / ⌘ + Enter 发送。运行中发送会排入 Queue，不会隐式打断当前 Turn。</p>}
  </form>;
  return planning ? <div className={`tutor-chatgpt-composer-area${planningIdle ? " idle" : ""}`}>{form}</div> : form;
}


function TypedRequestSeat({ request, draft, busy, disabled, onDraftChange, onSubmit, onApprove }: {
  request: TutorInteractionRequestItem; draft: RequestDraft; busy: boolean; disabled: boolean;
  onDraftChange: (draft: RequestDraft) => void; onSubmit: () => void; onApprove: (decision: "approve" | "deny") => void;
}) {
  return <section className="tutor-request-seat" aria-labelledby={`request-${request.id}`}>
    <strong className="tutor-request-seat-heading" id={`request-${request.id}`}>{request.prompt}</strong>
    {request.actor === "authority" ? <p className="tutor-muted-copy">此请求等待受信 authority 结果，普通 composer 与 Queue 控制保持锁定。</p> : request.kind === "approval" ? <div className="tutor-approval-card"><p>{request.presentation.summary}</p><span>风险级别：{request.presentation.risk_level}</span><div className="tutor-inline-actions"><Button variant="primary" busy={busy} disabled={disabled || busy} onClick={() => onApprove("approve")}>批准</Button><Button variant="outline" disabled={disabled || busy} onClick={() => onApprove("deny")}>拒绝</Button></div></div> : <form onSubmit={(event) => { event.preventDefault(); onSubmit(); }} className="tutor-request-form">
      <RequestControl request={request} draft={draft} disabled={disabled || busy} onDraftChange={onDraftChange} />
      <Button variant="primary" type="submit" busy={busy} disabled={disabled || busy || !requestDraftValid(request, draft)}>提交响应</Button>
    </form>}
  </section>;
}

function RequestControl({ request, draft, disabled, onDraftChange }: { request: Extract<TutorInteractionRequestItem, { kind: "elicitation" }>; draft: RequestDraft; disabled: boolean; onDraftChange: (draft: RequestDraft) => void }) {
  const presentation = request.presentation;
  if (presentation.type === "integer") return <Input className="tutor-request-input" type="number" min={presentation.minimum} max={presentation.maximum} step={presentation.step} value={typeof draft === "string" ? draft : ""} disabled={disabled} onChange={(event) => onDraftChange(event.target.value)} aria-label={request.prompt} />;
  if (presentation.type === "single_select") {
    const selected = typeof draft === "string" ? draft : "";
    return <fieldset className="tutor-request-options tutor-request-options-grid"><legend className="visually-hidden">{request.prompt}</legend>{presentation.options.map((option) => <label key={option.value}><input type="radio" name={`request-${request.id}`} value={option.value} checked={selected === option.value} disabled={disabled} onChange={() => onDraftChange(option.value)} /><span>{option.label}</span></label>)}</fieldset>;
  }
  if (presentation.type === "multi_select") {
    const selected = Array.isArray(draft) ? draft : [];
    return <fieldset className="tutor-request-options"><legend className="visually-hidden">{request.prompt}</legend>{presentation.options.map((option) => <label key={option.value}><input type="checkbox" checked={selected.includes(option.value)} disabled={disabled || (!selected.includes(option.value) && selected.length >= presentation.maximum_selections)} onChange={(event) => onDraftChange(event.target.checked ? [...selected, option.value] : selected.filter((value) => value !== option.value))} /><span>{option.label}</span></label>)}</fieldset>;
  }
  return <textarea className="tutor-request-textarea" rows={presentation.type === "text" && presentation.multiline ? 4 : 2} minLength={presentation.type === "text" ? presentation.minimum_length : undefined} maxLength={presentation.type === "text" ? presentation.maximum_length : undefined} value={typeof draft === "string" ? draft : ""} disabled={disabled} onChange={(event) => onDraftChange(event.target.value)} aria-label={request.prompt} />;
}

function QueueTray({ items, maxPending, activeTurn, paused, pauseReason, disabled, busyKey, editingId, editDraft, onBeginEdit, onCancelEdit, onEditDraft, onSaveEdit, onMove, onDelete, onSteer, onExecute, onResume }: {
  items: TutorQueuedInput[]; maxPending: number; activeTurn: TutorPublicTurn | null; paused: boolean; pauseReason: string | null; disabled: boolean; busyKey: string | null; editingId: string | null; editDraft: string;
  onBeginEdit: (item: TutorQueuedInput) => void; onCancelEdit: () => void; onEditDraft: (value: string) => void; onSaveEdit: (item: TutorQueuedInput) => void; onMove: (id: string, direction: -1 | 1) => void; onDelete: (item: TutorQueuedInput) => void; onSteer: (item: TutorQueuedInput) => void; onExecute: (item: TutorQueuedInput) => void; onResume: () => void;
}) {
  return <section className="tutor-queue-tray" aria-label="待处理 Queue"><header><div><IconQueue /><strong>Queue</strong><span>{items.length}/{maxPending}</span></div>{paused && <Button size="sm" variant="outline" disabled={disabled} busy={busyKey === "resume"} onClick={onResume}>继续队列</Button>}</header>{paused && <p className="tutor-queue-pause">队列已暂停：{displayQueuePauseReason(pauseReason)}</p>}{activeTurn && <p className="tutor-queue-active-hint">Steer 会影响当前处理并共享本 Turn 预算；中断并执行会结束当前 Turn 并创建 fresh Turn。</p>}<ol>{items.map((item, index) => <li key={item.item_id}>
    {editingId === item.item_id ? <div className="tutor-queue-edit"><textarea value={editDraft} onChange={(event) => onEditDraft(event.target.value)} disabled={disabled} rows={2} autoFocus /><div><Button size="sm" variant="primary" busy={busyKey === `edit:${item.item_id}`} disabled={disabled || !editDraft.trim()} onClick={() => onSaveEdit(item)}>保存</Button><Button size="sm" onClick={onCancelEdit}>取消</Button></div></div> : <><p>{item.content}</p><div className="tutor-queue-actions"><Button variant="icon" aria-label="编辑 Queue 项" title="编辑" disabled={disabled} icon={<IconEdit />} onClick={() => onBeginEdit(item)} /><Button variant="icon" aria-label="上移 Queue 项" title="上移" disabled={disabled || index === 0} icon={<IconChevronUp />} onClick={() => onMove(item.item_id, -1)} /><Button variant="icon" aria-label="下移 Queue 项" title="下移" disabled={disabled || index === items.length - 1} icon={<IconChevronDown />} onClick={() => onMove(item.item_id, 1)} /><Button variant="icon" aria-label="删除 Queue 项" title="删除" disabled={disabled} busy={busyKey === `delete:${item.item_id}`} icon={<IconDelete />} onClick={() => onDelete(item)} />{activeTurn && <Button size="sm" variant="outline" disabled={disabled} busy={busyKey === `steer:${item.item_id}`} onClick={() => onSteer(item)}>Steer</Button>}<Button size="sm" variant="primary" disabled={disabled} busy={busyKey === `execute:${item.item_id}`} title={activeTurn ? "中断当前 Turn，并以该 Queue 项创建 fresh Turn" : "以该 Queue 项创建 fresh Turn"} onClick={() => onExecute(item)}>{activeTurn ? "中断并执行" : "立即执行"}</Button></div></>}
  </li>)}</ol></section>;
}

function TimelineItem({ item, recentCompletion, writeEnabled, mutationBusy, onRetry }: {
  item: TutorHistoryItem;
  recentCompletion: TutorRecentCompletion | null;
  writeEnabled: boolean;
  mutationBusy: string | null;
  onRetry: (turnId: string) => void;
}) {
  if (item.kind === "process") return null;
  if (item.kind === "message") {
    if (item.role === "tutor") {
      return <TutorMessage item={item} recentCompletion={recentCompletion?.itemId === item.id ? recentCompletion : null} />;
    }
    return <article className="tutor-timeline-entry learner"><span className="tutor-timeline-label">你</span><div className="tutor-message-content"><p>{item.content}</p>{item.context_references.length > 0 && <TutorReferenceCards references={item.context_references} />}</div></article>;
  }
  if (item.kind === "error") {
    const migration = item.code === "TUTOR_LEGACY_CONTINUATION_REQUIRES_NEW_TURN";
    return <article className="tutor-timeline-entry error"><span className="tutor-timeline-label">{migration ? "迁移提示" : "处理失败"}</span><div className="tutor-message-content"><strong>{migration ? "旧等待步骤已安全终止" : item.code}</strong><p>{migration ? "请在普通 composer 中发送一条新消息继续；Desktop 不会回退到旧 continuation 写入路径。" : item.message}</p>{item.recoverable && item.turn_id && <Button size="sm" variant="outline" disabled={!writeEnabled} busy={mutationBusy === `retry:${item.turn_id}`} onClick={() => onRetry(item.turn_id!)}>重试本轮</Button>}</div></article>;
  }
  return <TutorRequestHistory item={item} recentCompletion={recentCompletion?.itemId === item.id ? recentCompletion : null} />;
}

function TutorRequestHistory({ item, recentCompletion }: { item: TutorInteractionRequestItem; recentCompletion: TutorRecentCompletion | null }) {
  const animateThinking = Boolean(recentCompletion?.streamedThinking);
  const thinking = useGraphemeTypewriter(item.public_thinking_text, {
    animate: animateThinking,
    initialText: recentCompletion ? (animateThinking ? recentCompletion.initialThinkingText : item.public_thinking_text) : item.public_thinking_text,
    resetKey: `request-thinking:${item.id}`,
    intervalMs: TUTOR_TEXT_REVEAL_INTERVAL_MS,
  });
  const promptTarget = recentCompletion && !thinking.complete ? "" : item.prompt;
  const promptReveal = useGraphemeTypewriter(promptTarget, {
    animate: recentCompletion !== null,
    initialText: recentCompletion ? "" : item.prompt,
    resetKey: `request-prompt:${item.id}`,
    intervalMs: TUTOR_TEXT_REVEAL_INTERVAL_MS,
  });
  const [expanded, setExpanded] = useState(recentCompletion !== null);
  const autoCollapsedRef = useRef(false);

  useEffect(() => {
    autoCollapsedRef.current = false;
    if (recentCompletion) setExpanded(true);
  }, [recentCompletion?.itemId]);
  useEffect(() => {
    if (!recentCompletion || autoCollapsedRef.current || !thinking.complete || promptTarget !== item.prompt || !promptReveal.complete) return;
    const timer = window.setTimeout(() => {
      autoCollapsedRef.current = true;
      setExpanded(false);
    }, TUTOR_THINKING_AUTO_COLLAPSE_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [item.prompt, promptReveal.complete, promptTarget, recentCompletion, thinking.complete]);

  return <article className="tutor-timeline-entry tutor tutor-request-history" data-request-state={item.state} data-turn-id={item.turn_id}>
    <span className="tutor-timeline-label">Tutor 请求</span>
    <div className="tutor-message-content">
      {item.public_thinking_text ? <TutorThinking messageId={item.id} text={thinking.text} expanded={expanded} complete={thinking.complete} onExpandedChange={setExpanded} /> : null}
      <p className={`tutor-answer-text${recentCompletion && !promptReveal.complete ? " is-streaming" : ""}`}>{promptReveal.text}</p>
    </div>
  </article>;
}

function TutorMessage({ item, recentCompletion }: { item: TutorHistoryMessage; recentCompletion: TutorRecentCompletion | null }) {
  if (item.runtime_output) {
    return <TutorRuntimeMessage item={item} output={item.runtime_output} />;
  }
  const animateThinking = Boolean(recentCompletion?.streamedThinking);
  const thinking = useGraphemeTypewriter(item.public_thinking_text, {
    animate: animateThinking,
    initialText: recentCompletion ? (animateThinking ? recentCompletion.initialThinkingText : item.public_thinking_text) : item.public_thinking_text,
    resetKey: `message-thinking:${item.id}`,
    intervalMs: TUTOR_TEXT_REVEAL_INTERVAL_MS,
  });
  const answerTarget = recentCompletion && !thinking.complete ? "" : item.content;
  const answer = useGraphemeTypewriter(answerTarget, {
    animate: recentCompletion !== null,
    initialText: recentCompletion ? "" : item.content,
    resetKey: `message-answer:${item.id}`,
    intervalMs: TUTOR_TEXT_REVEAL_INTERVAL_MS,
  });
  const [expanded, setExpanded] = useState(recentCompletion !== null);
  const autoCollapsedRef = useRef(false);

  useEffect(() => {
    autoCollapsedRef.current = false;
    if (recentCompletion) setExpanded(true);
  }, [recentCompletion?.itemId]);
  useEffect(() => {
    if (!recentCompletion || autoCollapsedRef.current || !thinking.complete || answerTarget !== item.content || !answer.complete) return;
    const timer = window.setTimeout(() => {
      autoCollapsedRef.current = true;
      setExpanded(false);
    }, TUTOR_THINKING_AUTO_COLLAPSE_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [answer.complete, answerTarget, item.content, recentCompletion, thinking.complete]);

  return <article className="tutor-timeline-entry tutor" data-turn-id={item.turn_id ?? undefined}>
    <span className="tutor-timeline-label">Tutor</span>
    <div className="tutor-message-content">
      {item.public_thinking_text ? <TutorThinking
        messageId={item.id}
        text={thinking.text}
        expanded={expanded}
        complete={thinking.complete}
        onExpandedChange={setExpanded}
      /> : null}
      <p className={`tutor-answer-text${recentCompletion && !answer.complete ? " is-streaming" : ""}`}>{answer.text}</p>
    </div>
  </article>;
}

function TutorRuntimeMessage({ item, output }: { item: TutorHistoryMessage; output: TutorRuntimeOutput }) {
  const [expanded, setExpanded] = useState(false);
  const reasoningText = runtimeReasoningText(output);
  const answerText = output.final_answer_item?.text || item.content;
  return <article className="tutor-timeline-entry tutor" data-turn-id={item.turn_id ?? undefined}>
    <span className="tutor-timeline-label">Tutor</span>
    <div className="tutor-message-content">
      {reasoningText ? <TutorThinking
        messageId={item.id}
        text={reasoningText}
        expanded={expanded}
        complete
        onExpandedChange={setExpanded}
      /> : null}
      <p className="tutor-answer-text">{answerText}</p>
    </div>
  </article>;
}

function TutorRunningPlaceholder({ turn, hasText, text, complete, runtimeOutput }: {
  turn: TutorPublicTurn;
  hasText: boolean;
  text: string;
  complete: boolean;
  runtimeOutput: TutorLiveRuntimeOutputState | null;
}) {
  const [expanded, setExpanded] = useState(true);
  const reasoningText = runtimeReasoningText(runtimeOutput);
  const answerItem = runtimeOutput?.final_answer_item ?? null;
  const hasRuntimeContent = Boolean(reasoningText || answerItem?.text);
  return <article className="tutor-timeline-entry tutor tutor-running-placeholder" data-turn-id={turn.turn_id}>
    <span className="tutor-timeline-label">Tutor</span>
    <div className="tutor-message-content">
      {reasoningText ? <TutorThinking
        messageId={`active-${turn.turn_id}`}
        text={reasoningText}
        expanded={expanded}
        complete={runtimeOutput?.reasoning_items.every((item) => item.state === "completed") ?? false}
        running
        onExpandedChange={setExpanded}
      /> : null}
      {answerItem?.text ? <p className={`tutor-answer-text${answerItem.state === "streaming" ? " is-streaming" : ""}`} aria-live="polite">{answerItem.text}</p> : null}
      {!hasRuntimeContent && (hasText ? <TutorThinking
        messageId={`active-legacy-${turn.turn_id}`}
        text={text}
        expanded={expanded}
        complete={complete}
        running
        onExpandedChange={setExpanded}
      /> : <div className="tutor-thinking-static" role="status" aria-label="think"><StateDot state="running" size={14} /><strong>think</strong></div>)}
    </div>
  </article>;
}

function TutorThinking({ messageId, text, expanded, complete, running = false, onExpandedChange }: {
  messageId: string;
  text: string;
  expanded: boolean;
  complete: boolean;
  running?: boolean;
  onExpandedChange: (expanded: boolean) => void;
}) {
  return <DisclosureRow
    className="tutor-thinking-disclosure"
    title="think"
    icon={<StateDot state={running && !complete ? "running" : "positive"} size={14} />}
    expanded={expanded}
    onExpandedChange={onExpandedChange}
    contentId={`tutor-thinking-${messageId}`}
  ><p className={`tutor-thinking-text${complete ? "" : " is-streaming"}`} aria-live="off">{text}</p></DisclosureRow>;
}

function TutorReferenceDraftChips({ references, disabled, onRemove }: { references: TutorComposerReference[]; disabled: boolean; onRemove?: (referenceId: string) => void }) { return <div className="tutor-reference-drafts" aria-label="待发送结构化引用">{references.map((reference) => <span key={reference.id} data-kind={reference.draft.kind}><span aria-hidden="true">{referenceIcon(reference.draft.kind)}</span><strong>{reference.label}</strong>{onRemove ? <button type="button" disabled={disabled} aria-label={`移除引用：${reference.label}`} onClick={() => onRemove(reference.id)}>×</button> : null}</span>)}</div>; }
function TutorReferenceCards({ references }: { references: TutorContextReference[] }) { return <div className="tutor-reference-cards" aria-label="本条消息的结构化引用">{references.map((reference) => <article key={reference.reference_id} data-kind={reference.kind}><span aria-hidden="true">{referenceIcon(reference.kind)}</span><div><strong>{referenceTitle(reference)}</strong><small>{referenceSummary(reference)}</small></div></article>)}</div>; }
function referenceIcon(kind: TutorContextReference["kind"] | TutorContextReferenceDraft["kind"]): string { return { lesson_selection: "§", exercise_feedback: "✓", execution_result: "⌘", review_feedback: "↺" }[kind]; }
function referenceTitle(reference: TutorContextReference): string { return { lesson_selection: "课程选段", exercise_feedback: "练习反馈", execution_result: "执行结果", review_feedback: "复习反馈" }[reference.kind]; }
function referenceSummary(reference: TutorContextReference): string { if (reference.kind === "lesson_selection") return reference.safe_excerpt; const summary = `${outcomeReferenceLabel(reference.outcome)} · ${Math.round(reference.score * 100)}% · ${reference.feedback_summary}`; return reference.kind === "execution_result" ? `${summary} · ${reference.execution_job_state}` : summary; }
function outcomeReferenceLabel(outcome: ExerciseAttemptOutcome): string { return { passed: "通过", failed: "未通过", timed_out: "超时", cancelled: "已取消", unavailable: "不可用", invalid: "无效" }[outcome]; }

type TutorRuntimeStreamPayload = Extract<TutorTurnOutputPayload, { output_version: "tutor_runtime_item_stream_v1" }>;

function runtimeOutputHasContent(output: TutorLiveRuntimeOutputState | null): boolean {
  return Boolean(runtimeReasoningText(output) || output?.final_answer_item?.text);
}

function runtimeReasoningText(output: TutorRuntimeOutput | TutorLiveRuntimeOutputState | null): string {
  return output?.reasoning_items.filter((item) => item.text.length > 0).map((item) => item.text).join("\n\n") ?? "";
}

function reduceRuntimeOutput(
  current: TutorLiveRuntimeOutputState | null,
  turnId: string,
  payload: TutorRuntimeStreamPayload,
): TutorLiveRuntimeOutputState | undefined {
  if (current && current.turnId === turnId && current.input_revision === payload.input_revision &&
      current.generation > payload.generation) return current;
  const sameGeneration = current && current.turnId === turnId &&
    current.input_revision === payload.input_revision && current.generation === payload.generation;
  const base: TutorLiveRuntimeOutputState = sameGeneration ? current : {
    turnId,
    output_version: "tutor_runtime_output_v1",
    input_revision: payload.input_revision,
    generation: payload.generation,
    reasoning_items: [],
    final_answer_item: null,
  };
  const existing = payload.channel === "reasoning"
    ? base.reasoning_items.find((item) => item.item_id === payload.item_id) ?? null
    : base.final_answer_item?.item_id === payload.item_id ? base.final_answer_item : null;
  if (existing && payload.chunk_sequence <= existing.last_sequence) return base;
  if (payload.operation === "discard") {
    return payload.channel === "reasoning"
      ? { ...base, reasoning_items: base.reasoning_items.filter((item) => item.item_id !== payload.item_id) }
      : { ...base, final_answer_item: base.final_answer_item?.item_id === payload.item_id ? null : base.final_answer_item };
  }
  let nextItem: TutorRuntimeOutputItem;
  if (payload.operation === "reset") {
    nextItem = { item_id: payload.item_id, text: "", state: "streaming", last_sequence: payload.chunk_sequence };
  } else if (payload.operation === "append") {
    const text = (existing?.text ?? "") + payload.text;
    if (text.length > 1_000_000) return undefined;
    nextItem = { item_id: payload.item_id, text, state: "streaming", last_sequence: payload.chunk_sequence };
  } else if (payload.operation === "complete") {
    const text = payload.text || existing?.text || "";
    nextItem = { item_id: payload.item_id, text, state: "completed", last_sequence: payload.chunk_sequence };
  } else {
    return undefined;
  }
  if (payload.channel === "final_answer") return { ...base, final_answer_item: nextItem };
  const reasoningItems = base.reasoning_items.some((item) => item.item_id === payload.item_id)
    ? base.reasoning_items.map((item) => item.item_id === payload.item_id ? nextItem : item)
    : [...base.reasoning_items, nextItem];
  return { ...base, reasoning_items: reasoningItems };
}

function mergeRuntimeOutputs(
  current: TutorLiveRuntimeOutputState,
  incoming: TutorLiveRuntimeOutputState,
): TutorLiveRuntimeOutputState {
  const currentById = new Map(current.reasoning_items.map((item) => [item.item_id, item]));
  const incomingIds = new Set(incoming.reasoning_items.map((item) => item.item_id));
  const reasoningItems = incoming.reasoning_items.map((item) => preferRuntimeItem(currentById.get(item.item_id) ?? null, item) ?? item);
  for (const item of current.reasoning_items) {
    if (!incomingIds.has(item.item_id)) reasoningItems.push(item);
  }
  return {
    ...incoming,
    reasoning_items: reasoningItems,
    final_answer_item: preferRuntimeItem(current.final_answer_item, incoming.final_answer_item),
  };
}

function preferRuntimeItem(
  current: TutorRuntimeOutputItem | null,
  incoming: TutorRuntimeOutputItem | null,
): TutorRuntimeOutputItem | null {
  if (!current) return incoming;
  if (!incoming) return current;
  if (current.item_id !== incoming.item_id) return incoming;
  if (current.last_sequence > incoming.last_sequence) return current;
  if (!incoming.text && current.text) {
    return incoming.state === "completed"
      ? { ...current, state: "completed", last_sequence: incoming.last_sequence }
      : current;
  }
  if (current.text.startsWith(incoming.text) && current.state === "streaming" && incoming.state === "streaming") return current;
  return incoming;
}

function dedupeTimeline(items: TutorHistoryItem[]): TutorHistoryItem[] { const seen = new Set<string>(); return items.filter((item) => { const key = item.kind + ":" + item.id; if (seen.has(key)) return false; seen.add(key); return true; }); }
function reconcileVisibleTimeline(items: TutorHistoryItem[]): TutorHistoryItem[] {
  const deduped = dedupeTimeline(items);
  const formalTutorTurnIds = new Set(deduped.flatMap((item) =>
    item.kind === "message" && item.role === "tutor" && item.turn_id ? [item.turn_id] : [],
  ));
  return deduped.filter((item) =>
    (item.kind !== "elicitation" && item.kind !== "approval") || !formalTutorTurnIds.has(item.turn_id),
  );
}
function initialRequestDraft(request: TutorInteractionRequestItem | null): RequestDraft { if (!request || request.kind === "approval") return ""; const p = request.presentation; if (p.type === "integer") return p.recommended === null ? "" : String(p.recommended); if (p.type === "single_select") return p.recommended ?? ""; if (p.type === "multi_select") return p.recommended; return ""; }
function requestDraftValid(request: TutorInteractionRequestItem, draft: RequestDraft): boolean { if (request.kind === "approval") return true; if (request.presentation.type === "multi_select") return Array.isArray(draft) && draft.length > 0; if (typeof draft !== "string" || !draft.trim()) return false; if (request.presentation.type === "integer") { const value = Number(draft); return Number.isFinite(value) && value >= request.presentation.minimum && value <= request.presentation.maximum; } if (request.presentation.type === "text") return draft.trim().length >= request.presentation.minimum_length && draft.trim().length <= request.presentation.maximum_length; return true; }
function presentationFieldKey(presentation: Extract<TutorInteractionRequestItem, { kind: "elicitation" }>["presentation"]): string | null { return presentation.type === "approval" ? null : presentation.field_key; }
function planningQuestionKey(value: string | null): Extract<TutorInteractionResponseDraft, { kind: "planning_input" }>["question_key"] | null { return value === "language_id" || value === "goal_text" || value === "target_level" || value === "weekly_minutes" || value === "experience_level" || value === "teaching_preferences" || value === "pace_constraints" ? value : null; }
function displayControlState(state: string, turn: TutorPublicTurn | null): string { if (turn?.status === "in_progress") return "正在运行"; return { idle: "空闲", running: "正在运行", waiting: "等待类型化输入", queue_paused: "Queue 已暂停" }[state] ?? state; }
function displayQueuePauseReason(reason: string | null): string { return { pending_request: "等待类型化请求", interrupted: "当前 Turn 已停止", failed: "上一 Turn 失败" }[reason ?? ""] ?? "等待显式恢复"; }
function displayStreamStatus(status: string): string { return { idle: "待命", connecting: "连接中", streaming: "已连接", reconnecting: "正在重连", error: "需要恢复" }[status] ?? status; }
function createTutorActionId(prefix: string): string { const uuid = globalThis.crypto?.randomUUID?.(); return uuid ? `${prefix}:${uuid}` : `${prefix}:${Date.now()}:${Math.random().toString(16).slice(2)}`; }
