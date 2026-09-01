import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type RefObject } from "react";

import {
  acceptTutorConversationInput, acceptTutorFirstTurn, buildTutorConversationEventsUrl,
  correctTutorMemory, deleteTutorMemory, deleteTutorQueueItem, dismissTutorInbox,
  editTutorQueueItem, executeTutorQueueItem, fetchTutorActivity, fetchTutorArtifact, fetchTutorConversationSnapshot,
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
  TeachingActionDescriptor, TeachingActionShelf, TeachingSessionGroupProjection,
  TutorPublicArtifactItem, TutorPublicBranchGroup, TutorPublicTurn, TutorQueuedInput, TutorRuntimeOutput, TutorRuntimeOutputItem,
  TutorThreadTurnV2Capability, TutorTurnOutputPayload, UserProfile,
} from "../../types";
import {
  Button, DisclosureRow, DshDerivedRoot, IconChevronDown, IconChevronUp, IconDelete,
  IconEdit, IconQueue, IconSend, IconStop, Input, StateDot,
} from "../../ui/dsh-derived";
import { ComposerActionShelf } from "./ComposerActionShelf";
import type { TutorArtifactActionRequest } from "./artifacts";
import { TutorActivityPanel } from "./TutorActivityPanel";
import { TutorMemoryPanel } from "./TutorMemoryPanel";
import { TutorPlanPreferencesPanel } from "./TutorPlanPreferencesPanel";
import {
  Boundary, Composer, groupTeachingTimeline, QueueTray, TeachingSessionTimeline,
  TimelineSequence, TutorRunningPlaceholder, TypedRequestSeat,
} from "./TutorConversationParts";
import {
  artifactIdsInTimeline, clearPersistedRequestDraft, createTutorActionId, displayControlState, displayStreamStatus,
  initialRequestDraft, mergeActiveArtifactIntoTimeline, mergeRuntimeOutputs, persistRequestDraft, planningQuestionKey,
  presentationFieldKey, reconcileVisibleTimeline, reduceRuntimeOutput, runtimeOutputHasContent,
  TUTOR_TEXT_REVEAL_INTERVAL_MS, type RequestDraft, type TutorComposerReference,
  type TutorLiveRuntimeOutputState, type TutorRecentCompletion,
} from "./tutorConversationModel";

export { groupTeachingTimeline } from "./TutorConversationParts";
export type { TutorComposerReference } from "./tutorConversationModel";

export type TutorConversationSurfaceProps = {
  user: UserProfile | null; enabled?: boolean; isActive?: boolean;
  selectedConversationId: string | null; onSelectConversation: (conversationId: string | null) => void;
  onConversationsChanged?: () => void; mode?: "general" | "plan_drafting"; showControls?: boolean;
  planningComposerPlaceholder?: string; composerVariant?: "card" | "compact";
  learningScope?: LearningScopeInput; scopeLabel?: string; contextReferences?: TutorComposerReference[];
  onRemoveContextReference?: (referenceId: string) => void;
  onReferencesAccepted?: (references: TutorContextReference[]) => void;
  onHistoricalMessageReference?: (reference: TutorContextReferenceDraft, label: string) => void;
  activeTeachingSessionId?: string | null;
  teachingActionShelf?: TeachingActionShelf | null;
  pendingTeachingActionKey?: string | null;
  onTeachingAction?: (descriptor: TeachingActionDescriptor) => void;
  onTeachingAuthorityChanged?: () => void;
  onArtifactAction?: (request: TutorArtifactActionRequest) => void;
};
type LoadStatus = "idle" | "loading" | "ready" | "error";
type PreferenceUpdate = { inferredMemoryEnabled?: boolean; expectedMemorySettingVersion?: string; proactivePaused?: boolean };
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
const PAGE_SIZE = 40;
const TUTOR_THINKING_STABILITY_DELAY_MS = 350;

export function TutorConversationSurface({
  user, enabled = false, isActive = true, selectedConversationId, onSelectConversation,
  onConversationsChanged, mode = "general", showControls = true, planningComposerPlaceholder, composerVariant = "card", learningScope, scopeLabel,
  contextReferences = [], onRemoveContextReference, onReferencesAccepted, onHistoricalMessageReference,
  activeTeachingSessionId = null, teachingActionShelf = null, pendingTeachingActionKey = null,
  onTeachingAction, onTeachingAuthorityChanged, onArtifactAction,
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
  const [teachingSessionGroups, setTeachingSessionGroups] = useState<TeachingSessionGroupProjection[]>([]);
  const [branches, setBranches] = useState<TutorPublicBranchGroup[]>([]);
  const [newArtifactIds, setNewArtifactIds] = useState<Set<string>>(() => new Set());
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
  const hydratedConversationRef = useRef<string | null>(null);
  const artifactIdsRef = useRef<Set<string>>(new Set());
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
    const mergedTimeline = mergeActiveArtifactIntoTimeline(
      snapshot.timeline.filter((item) => item.kind !== "process"),
      placement === "replace" ? snapshot.active_artifact ?? null : null,
    );
    const visible = reconcileVisibleTimeline(mergedTimeline.reverse());
    const incomingArtifactIds = artifactIdsInTimeline(visible);
    if (placement === "replace") {
      const initialHydration = hydratedConversationRef.current !== snapshot.conversation.conversation_id;
      if (initialHydration) {
        hydratedConversationRef.current = snapshot.conversation.conversation_id;
        setNewArtifactIds(new Set());
        scrollToLatestRef.current = true;
      } else {
        setNewArtifactIds(new Set([...incomingArtifactIds].filter((id) => !artifactIdsRef.current.has(id))));
      }
      artifactIdsRef.current = incomingArtifactIds;
    } else {
      artifactIdsRef.current = new Set([...artifactIdsRef.current, ...incomingArtifactIds]);
    }
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
    setTeachingSessionGroups(snapshot.teaching_sessions ?? []);
    setBranches(snapshot.branches ?? []);
    setStreamCursor(snapshot.stream_cursor);
    if (placement === "replace") {
      setHistoryCursor(snapshot.next_cursor); setHistoryHasMore(snapshot.has_more);
      setLoadStatus("ready"); setLoadError(null);
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
  const loadArtifactDetail = useCallback((artifact: TutorPublicArtifactItem) => {
    if (!userId) return Promise.reject(new Error("Tutor Artifact detail requires an active user"));
    return fetchTutorArtifact({
      userId,
      conversationId: artifact.conversation_id,
      artifactId: artifact.id,
    });
  }, [userId]);
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
      else { scheduleRefresh(); onConversationsChanged?.(); onTeachingAuthorityChanged?.(); }
    },
    onResetRequired: requireThinkingSnapshot,
  });

  useEffect(() => { const controller = new AbortController(); void loadCapability(controller.signal); return () => controller.abort(); }, [loadCapability]);
  useEffect(() => {
    requestRef.current?.abort();
    if (refreshTimerRef.current !== null) window.clearTimeout(refreshTimerRef.current);
    setComposerText(""); setActionError(null); setEditingQueueId(null); setRequestDraft("");
    setBranches([]); setNewArtifactIds(new Set()); hydratedConversationRef.current = null; artifactIdsRef.current = new Set();
    setRecentCompletion(null); setStableThinkingKey(null); replaceLiveThinking(null); replaceLiveRuntimeOutput(null); displayedThinkingRef.current = "";
    thinkingRecoveryPendingRef.current = false;
    activeTurnRef.current = null; setActiveTurn(null); setThinkingTurn(null);
    if (!mayReadTutor || !selectedConversationId) {
      setTimeline([]); setLoadStatus("idle"); setLoadError(null);
      setQueue([]); setPendingRequest(null); setTeachingSessionGroups([]); setStreamCursor(null); return;
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
  function updateRequestDraft(draft: RequestDraft) {
    setRequestDraft(draft);
    persistRequestDraft(pendingRequest, draft);
  }
  function respondToPendingRequest(response: TutorInteractionResponseDraft) {
    if (!userId || !selectedConversationId || !pendingRequest) return;
    const answeredRequest = pendingRequest;
    void runMutation(`request:${answeredRequest.id}`, async () => {
      const accepted = await respondToTutorInteractionRequest({ userId, conversationId: selectedConversationId, itemId: answeredRequest.id, expectedRequestVersion: answeredRequest.version, response, clientActionId: createTutorActionId("tutor-request-response") });
      clearPersistedRequestDraft(answeredRequest);
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
  const compactComposer = planning || composerVariant === "compact";
  const workspaceClassName = showControls ? "tutor-workspace" : `tutor-workspace tutor-conversation-only${planningIdle ? " tutor-conversation-idle" : ""}`;
  const mutationsLocked = !writeEnabled || Boolean(pendingRequest) || Boolean(mutationBusy);
  const running = activeTurn?.status === "in_progress" && controlState === "running";
  const projectedTeachingActions = teachingActionShelf
    ? [teachingActionShelf.primary_action, ...teachingActionShelf.secondary_actions, ...teachingActionShelf.overflow_actions].filter(Boolean).length
    : 0;
  const hasTeachingActionShelf = Boolean(
    !running && onTeachingAction && teachingActionShelf
    && teachingActionShelf.state !== "runtime_active"
    && teachingActionShelf.state !== "blocking_request"
    && projectedTeachingActions > 0,
  );
  const sendLabel = composerStatus === "submitting" ? "正在确认……" : running ? "加入 Queue" : selectedConversationId ? "发送消息" : "开始对话";


  const groupedTimeline = groupTeachingTimeline(timeline, teachingSessionGroups, activeTeachingSessionId, branches);

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
        <TeachingSessionTimeline
          groups={groupedTimeline.history}
          legacyItems={groupedTimeline.legacy}
          branches={branches}
          conversationId={selectedConversationId ?? ""}
          newArtifactIds={newArtifactIds}
          recentCompletion={recentCompletion}
          writeEnabled={writeEnabled}
          mutationBusy={mutationBusy}
          onRetry={(turnId) => { if (!userId || !selectedConversationId) return; void runMutation(`retry:${turnId}`, () => retryTutorTurn({ userId, conversationId: selectedConversationId, turnId, expectedControlVersion: controlVersion, clientActionId: createTutorActionId("tutor-turn-retry") })); }}
          onReference={onHistoricalMessageReference}
          onArtifactAction={onArtifactAction}
          loadArtifactDetail={loadArtifactDetail}
        />
        <TimelineSequence
          items={groupedTimeline.current}
          branches={branches}
          conversationId={selectedConversationId ?? ""}
          newArtifactIds={newArtifactIds}
          recentCompletion={recentCompletion}
          writeEnabled={writeEnabled}
          mutationBusy={mutationBusy}
          onRetry={(turnId) => { if (!userId || !selectedConversationId) return; void runMutation(`retry:${turnId}`, () => retryTutorTurn({ userId, conversationId: selectedConversationId, turnId, expectedControlVersion: controlVersion, clientActionId: createTutorActionId("tutor-turn-retry") })); }}
          onArtifactAction={onArtifactAction}
          loadArtifactDetail={loadArtifactDetail}
        />
        {thinkingTurn && (running || Boolean(liveThinking?.receivedText) || runtimeOutputHasContent(liveRuntimeOutput)) ? <TutorRunningPlaceholder
          key={`${thinkingTurn.turn_id}:${liveRuntimeOutput?.generation ?? liveThinking?.generation ?? "pending"}`}
          turn={thinkingTurn}
          hasText={Boolean(liveThinkingTargetText)}
          text={liveThinkingTypewriter.text}
          complete={Boolean(liveThinking?.complete && liveThinkingTypewriter.complete)}
          runtimeOutput={liveRuntimeOutput}
        /> : null}
      </section>

      {pendingRequest ? <TypedRequestSeat request={pendingRequest} draft={requestDraft} busy={mutationBusy === `request:${pendingRequest.id}`} disabled={!writeEnabled} onDraftChange={updateRequestDraft} onSubmit={submitRequestDraft} onApprove={(decision) => respondToPendingRequest({ kind: "approval", proposal_identity: pendingRequest.kind === "approval" ? pendingRequest.presentation.proposal_id : "", decision })} /> : <>
        {selectedConversationId && queue.length > 0 && <QueueTray
          items={queue} maxPending={maxPending} activeTurn={activeTurn} paused={queuePaused} pauseReason={queuePauseReason}
          disabled={mutationsLocked} busyKey={mutationBusy} editingId={editingQueueId} editDraft={queueEditDraft}
          onBeginEdit={(item) => { setEditingQueueId(item.item_id); setQueueEditDraft(item.content); }} onCancelEdit={() => setEditingQueueId(null)} onEditDraft={setQueueEditDraft} onSaveEdit={saveQueueEdit} onMove={reorder}
          onDelete={(item) => { if (!userId || !selectedConversationId) return; void runMutation(`delete:${item.item_id}`, () => deleteTutorQueueItem({ userId, conversationId: selectedConversationId, itemId: item.item_id, expectedControlVersion: controlVersion, expectedItemVersion: item.version, clientActionId: createTutorActionId("tutor-queue-delete") })); }}
          onSteer={(item) => { if (!userId || !selectedConversationId || !activeTurn) return; void runMutation(`steer:${item.item_id}`, () => steerTutorQueueItem({ userId, conversationId: selectedConversationId, itemId: item.item_id, expectedTurnId: activeTurn.turn_id, expectedInputRevision: activeTurn.input_revision, expectedControlVersion: controlVersion, clientActionId: createTutorActionId("tutor-queue-steer") })); }}
          onExecute={(item) => { if (!userId || !selectedConversationId) return; void runMutation(`execute:${item.item_id}`, () => executeTutorQueueItem({ userId, conversationId: selectedConversationId, itemId: item.item_id, expectedControlVersion: controlVersion, clientActionId: createTutorActionId("tutor-queue-execute") })); }}
          onResume={() => { if (!userId || !selectedConversationId) return; void runMutation("resume", () => resumeTutorQueue({ userId, conversationId: selectedConversationId, expectedControlVersion: controlVersion, clientActionId: createTutorActionId("tutor-queue-resume") })); }}
        />}
        <div className={"tutor-composer-dock" + (hasTeachingActionShelf ? " has-action-shelf" : "")}>
          {running && selectedConversationId && activeTurn ? <div className="tutor-running-controls" role="status"><span>{activeTurn.input_revision > 0 ? "当前 Turn 正在运行；发送新消息会进入 Queue。" : "教学控制正在运行；完成前由 runtime controls 接管 Action Shelf。"}</span>{activeTurn.input_revision > 0 ? <Button variant="outline" size="sm" icon={<IconStop />} busy={mutationBusy === "interrupt"} disabled={!writeEnabled || Boolean(mutationBusy)} onClick={() => { if (!userId) return; void runMutation("interrupt", () => interruptTutorTurn({ userId, conversationId: selectedConversationId, expectedTurnId: activeTurn.turn_id, expectedInputRevision: activeTurn.input_revision, expectedControlVersion: controlVersion, clientActionId: createTutorActionId("tutor-turn-interrupt") })); }}>停止</Button> : null}</div> : hasTeachingActionShelf && onTeachingAction ? <ComposerActionShelf projection={teachingActionShelf} pendingActionKey={pendingTeachingActionKey} onAction={onTeachingAction} /> : null}
        <Composer planning={planning} compact={compactComposer} planningIdle={planningIdle} planningPlaceholder={planningComposerPlaceholder} selectedConversationId={selectedConversationId} text={composerText} status={composerStatus} disabled={!writeEnabled} sendLabel={sendLabel} contextReferences={contextReferences} composerRef={composerRef} onTextChange={setComposerText} onKeyDown={handleComposerKeyDown} onSubmit={() => void submitComposer()} onRemoveReference={onRemoveContextReference} />
        </div>
      </>}
    </section>

    {showControls && writeEnabled && <aside className="tutor-side-column" aria-label="Tutor 学习控制">
      <TutorActivityPanel activity={activity} inbox={inbox} loading={controlsStatus === "loading"} errorMessage={controlsStatus === "error" ? controlsError : null} busyInboxId={busyInboxId} onRetry={() => void loadControls()} onMarkRead={handleMarkInboxRead} onDismiss={handleDismissInbox} />
      <TutorMemoryPanel memory={memory} loading={controlsStatus === "loading"} errorMessage={controlsStatus === "error" ? controlsError : null} busyEntryId={busyMemoryId} onRetry={() => void loadControls()} onCorrect={handleCorrectMemory} onDelete={handleDeleteMemory} />
      <TutorPlanPreferencesPanel plans={plans} preferences={preferences} loading={controlsStatus === "loading"} errorMessage={controlsStatus === "error" ? controlsError : null} pendingAction={pendingPlanOrPreferenceAction} onRetry={() => void loadControls()} onRollback={handleRollbackPlan} onUpdatePreferences={handleUpdatePreferences} />
    </aside>}
  </main></DshDerivedRoot>;
}
