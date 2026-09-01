import type {
  TutorContextReferenceDraft, TutorHistoryItem, TutorInteractionRequestItem, TutorPublicArtifactItem,
  TutorInteractionResponseDraft, TutorPublicBranchGroup, TutorPublicProcess, TutorPublicTurn, TutorRuntimeOutput,
  TutorRuntimeOutputItem, TutorTurnOutputPayload,
} from "../../types";

export type RequestDraft = string | string[];
export type TutorComposerReference = { id: string; draft: TutorContextReferenceDraft; label: string };
export type TutorLiveRuntimeOutputState = TutorRuntimeOutput & { turnId: string };
export type TutorRecentCompletion = {
  itemId: string;
  turnId: string;
  initialThinkingText: string;
  streamedThinking: boolean;
};

export const TUTOR_TEXT_REVEAL_INTERVAL_MS = 18;
export const TUTOR_THINKING_AUTO_COLLAPSE_DELAY_MS = 240;

type TutorRuntimeStreamPayload = Extract<TutorTurnOutputPayload, { output_version: "tutor_runtime_item_stream_v1" }>;

export function runtimeOutputHasContent(output: TutorLiveRuntimeOutputState | null): boolean {
  return Boolean(runtimeReasoningText(output) || output?.final_answer_item?.text);
}

export function runtimeReasoningText(output: TutorRuntimeOutput | TutorLiveRuntimeOutputState | null): string {
  return output?.reasoning_items.filter((item) => item.text.length > 0).map((item) => item.text).join("\n\n") ?? "";
}

export function reduceRuntimeOutput(
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

export function mergeRuntimeOutputs(
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

export function preferRuntimeItem(
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

export function dedupeTimeline(items: TutorHistoryItem[]): TutorHistoryItem[] { const seen = new Set<string>(); return items.filter((item) => { const key = item.kind + ":" + item.id; if (seen.has(key)) return false; seen.add(key); return true; }); }
export function reconcileVisibleTimeline(items: TutorHistoryItem[]): TutorHistoryItem[] {
  const deduped = dedupeTimeline(items);
  const formalTutorTurnIds = new Set(deduped.flatMap((item) =>
    item.kind === "message" && item.role === "tutor" && item.turn_id ? [item.turn_id] : [],
  ));
  return deduped.filter((item) =>
    (item.kind !== "elicitation" && item.kind !== "approval") || !formalTutorTurnIds.has(item.turn_id),
  );
}
export function initialRequestDraft(request: TutorInteractionRequestItem | null): RequestDraft {
  if (!request || request.kind === "approval") return "";
  const stored = readPersistedRequestDraft(request);
  if (stored !== null) return stored;
  const p = request.presentation;
  if (p.type === "integer") return p.recommended === null ? "" : String(p.recommended);
  if (p.type === "single_select") return p.recommended ?? "";
  if (p.type === "multi_select") return p.recommended;
  return "";
}
export function requestDraftStorageKey(request: TutorInteractionRequestItem): string { return `aearn.tutor-request-draft:${request.id}:${request.version}`; }
export function persistRequestDraft(request: TutorInteractionRequestItem | null, draft: RequestDraft) {
  if (!request || request.kind === "approval" || (request.presentation.type !== "single_select" && request.presentation.type !== "multi_select")) return;
  try { window.sessionStorage.setItem(requestDraftStorageKey(request), JSON.stringify(draft)); } catch { /* storage is best-effort */ }
}
export function clearPersistedRequestDraft(request: TutorInteractionRequestItem) {
  try { window.sessionStorage.removeItem(requestDraftStorageKey(request)); } catch { /* storage is best-effort */ }
}
export function readPersistedRequestDraft(request: TutorInteractionRequestItem): RequestDraft | null {
  if (request.kind === "approval" || (request.presentation.type !== "single_select" && request.presentation.type !== "multi_select")) return null;
  try {
    const raw = window.sessionStorage.getItem(requestDraftStorageKey(request));
    if (raw === null) return null;
    const parsed: unknown = JSON.parse(raw);
    const allowed = new Set(request.presentation.options.map((option) => option.value));
    if (request.presentation.type === "single_select") return typeof parsed === "string" && allowed.has(parsed) ? parsed : null;
    return Array.isArray(parsed) && parsed.length > 0 && parsed.length <= request.presentation.maximum_selections && parsed.every((value) => typeof value === "string" && allowed.has(value)) ? parsed : null;
  } catch { return null; }
}
export function requestDraftValid(request: TutorInteractionRequestItem, draft: RequestDraft): boolean { if (request.kind === "approval") return true; if (request.presentation.type === "multi_select") return Array.isArray(draft) && draft.length > 0; if (typeof draft !== "string" || !draft.trim()) return false; if (request.presentation.type === "integer") { const value = Number(draft); return Number.isFinite(value) && value >= request.presentation.minimum && value <= request.presentation.maximum; } if (request.presentation.type === "text") return draft.trim().length >= request.presentation.minimum_length && draft.trim().length <= request.presentation.maximum_length; return true; }
export function presentationFieldKey(presentation: Extract<TutorInteractionRequestItem, { kind: "elicitation" }>["presentation"]): string | null { return presentation.type === "approval" ? null : presentation.field_key; }
export function planningQuestionKey(value: string | null): Extract<TutorInteractionResponseDraft, { kind: "planning_input" }>["question_key"] | null { return value === "language_id" || value === "goal_text" || value === "target_level" || value === "weekly_minutes" || value === "experience_level" || value === "teaching_preferences" || value === "pace_constraints" ? value : null; }
export function displayControlState(state: string, turn: TutorPublicTurn | null): string { if (turn?.status === "in_progress") return "正在运行"; return { idle: "空闲", running: "正在运行", waiting: "等待类型化输入", queue_paused: "Queue 已暂停" }[state] ?? state; }
export function displayQueuePauseReason(reason: string | null): string { return { pending_request: "等待类型化请求", interrupted: "当前 Turn 已停止", failed: "上一 Turn 失败" }[reason ?? ""] ?? "等待显式恢复"; }
export function displayStreamStatus(status: string): string { return { idle: "待命", connecting: "连接中", streaming: "已连接", reconnecting: "正在重连", error: "需要恢复" }[status] ?? status; }
export function createTutorActionId(prefix: string): string { const uuid = globalThis.crypto?.randomUUID?.(); return uuid ? `${prefix}:${uuid}` : `${prefix}:${Date.now()}:${Math.random().toString(16).slice(2)}`; }

export type TutorTimelineRenderNode =
  | { kind: "item"; item: TutorHistoryItem; terminalCollapseMarker: string | null }
  | { kind: "branch"; branch: TutorPublicBranchGroup; items: TutorHistoryItem[] };

export function mergeActiveArtifactIntoTimeline(
  timeline: TutorHistoryItem[],
  activeArtifact: TutorPublicArtifactItem | null,
): TutorHistoryItem[] {
  if (!activeArtifact || timeline.some((item) => item.kind === "artifact" && item.id === activeArtifact.id)) return timeline;
  return [activeArtifact, ...timeline];
}

export function groupTimelineAroundArtifacts(
  timeline: TutorHistoryItem[],
  branches: TutorPublicBranchGroup[],
): TutorTimelineRenderNode[] {
  if (branches.length === 0) {
    return timeline.map((item, index) => ({
      kind: "item",
      item,
      terminalCollapseMarker: item.kind === "artifact" ? nextMainlineLearnerId(timeline, index, item.terminal_at) : null,
    }));
  }
  const itemByIdentity = new Map(timeline.map((item) => [historyIdentity(item), item]));
  const anchorIds = new Set(timeline.flatMap((item) => item.kind === "artifact" ? [item.id] : []));
  const acceptedBranches: TutorPublicBranchGroup[] = [];
  const seenBranches = new Set<string>();
  for (const branch of branches) {
    if (seenBranches.has(branch.branch_id) || !anchorIds.has(branch.anchor_artifact_id)) continue;
    seenBranches.add(branch.branch_id);
    acceptedBranches.push(branch);
  }
  const branchItemIdentities = new Set<string>();
  for (const branch of acceptedBranches) {
    for (const reference of branch.items) {
      const identity = `${reference.item_kind}:${reference.item_id}`;
      if (itemByIdentity.has(identity)) branchItemIdentities.add(identity);
    }
  }
  const mainline = timeline.filter((item) => !branchItemIdentities.has(historyIdentity(item)));
  const branchesByAnchor = new Map<string, TutorPublicBranchGroup[]>();
  for (const branch of acceptedBranches) {
    branchesByAnchor.set(branch.anchor_artifact_id, [...(branchesByAnchor.get(branch.anchor_artifact_id) ?? []), branch]);
  }
  const nodes: TutorTimelineRenderNode[] = [];
  mainline.forEach((item, index) => {
    nodes.push({
      kind: "item",
      item,
      terminalCollapseMarker: item.kind === "artifact" ? nextMainlineLearnerId(mainline, index, item.terminal_at) : null,
    });
    if (item.kind !== "artifact") return;
    for (const branch of branchesByAnchor.get(item.id) ?? []) {
      const branchItems = branch.items.flatMap((reference) => {
        const matched = itemByIdentity.get(`${reference.item_kind}:${reference.item_id}`);
        return matched ? [matched] : [];
      });
      nodes.push({ kind: "branch", branch, items: branchItems });
    }
  });
  return nodes;
}

export function artifactIdsInTimeline(timeline: TutorHistoryItem[]): Set<string> {
  return new Set(timeline.flatMap((item) => item.kind === "artifact" ? [item.id] : []));
}

function historyIdentity(item: TutorHistoryItem): string {
  return `${item.kind}:${item.id}`;
}

function nextMainlineLearnerId(timeline: TutorHistoryItem[], artifactIndex: number, terminalAt: string | null): string | null {
  if (!terminalAt) return null;
  const terminalTime = Date.parse(terminalAt);
  if (!Number.isFinite(terminalTime)) return null;
  for (let index = artifactIndex + 1; index < timeline.length; index += 1) {
    const item = timeline[index];
    if (item?.kind !== "message" || item.role !== "learner" || !item.created_at) continue;
    const learnerTime = Date.parse(item.created_at);
    if (Number.isFinite(learnerTime) && learnerTime >= terminalTime) return item.id;
  }
  return null;
}
