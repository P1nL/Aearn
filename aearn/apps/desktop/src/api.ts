import {
  ApiRequestError,
  type ApiError,
  type ApiHealth,
  type HarnessCutoverDecision,
  type LanguageCourse,
  type TutorActivityItem,
  type TutorContinuationKind,
  type TutorConversationHistoryResponse,
  type TutorConversationListResponse,
  type TutorConversationSummary,
  type TutorForegroundRun,
  type TutorHistoryItem,
  type TutorInboxItem,
  type TutorInputAcceptedResponse,
  type TutorMemoryItem,
  type TutorPlanRevision,
  type TutorPlanRevisionList,
  type TutorPreferences,
  type TutorPublicProcess,
  type TutorPublicProcessStep,
  type TutorRunState,
  type UserProfile,
} from "./types";

export const API_BASE_URL = "http://127.0.0.1:8001";

export async function fetchApiHealth(signal?: AbortSignal): Promise<ApiHealth> {
  const payload = await requestJson(`${API_BASE_URL}/health`, { signal });
  if (!isApiHealth(payload)) throw new Error("Health check returned an invalid payload");
  return payload;
}

export async function fetchLanguageCourses(signal?: AbortSignal): Promise<LanguageCourse[]> {
  const payload = await requestJson(`${API_BASE_URL}/api/language-courses`, { signal });
  if (!isRecord(payload) || !Array.isArray(payload.items)) throw new Error("Course catalog returned an invalid payload");
  const items = payload.items.map(toLanguageCourse);
  if (items.some((item) => item === null)) throw new Error("Course catalog returned an invalid item");
  return items.filter((item): item is LanguageCourse => item !== null);
}

export async function createUser(displayName: string, signal?: AbortSignal): Promise<UserProfile> {
  const payload = await requestJson(`${API_BASE_URL}/api/users`, {
    method: "POST",
    body: JSON.stringify({ display_name: displayName }),
    signal,
  });
  if (!isRecord(payload) || !isUserProfile(payload.user)) throw new Error("User API returned an invalid payload");
  return payload.user;
}

export async function fetchUserProfile(userId: string, signal?: AbortSignal): Promise<UserProfile> {
  const payload = await requestJson(`${API_BASE_URL}/api/users/${encodeURIComponent(userId)}`, { signal });
  if (!isRecord(payload) || !isUserProfile(payload.user)) throw new Error("User profile API returned an invalid payload");
  return payload.user;
}

export async function fetchHarnessCutover(userId: string, signal?: AbortSignal): Promise<HarnessCutoverDecision> {
  const query = new URLSearchParams({ user_id: userId });
  const payload = await requestJson(`${API_BASE_URL}/api/harness/cutover?${query.toString()}`, { signal });
  if (!isHarnessCutoverDecision(payload)) throw new Error("Harness cutover API returned an invalid payload");
  return payload;
}

export async function confirmHarnessCutover(input: {
  userId: string;
  cutoverVersion: string;
  summaryVersion: number;
  previewNonce: string;
  summaryHash: string;
  clientActionId: string;
}): Promise<HarnessCutoverDecision> {
  const payload = await requestJson(`${API_BASE_URL}/api/harness/cutover/confirm`, {
    method: "POST",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({
      user_id: input.userId,
      cutover_version: input.cutoverVersion,
      summary_version: input.summaryVersion,
      preview_nonce: input.previewNonce,
      summary_hash: input.summaryHash,
      client_action_id: input.clientActionId,
      confirm: true,
    }),
  });
  if (!isHarnessCutoverDecision(payload)) throw new Error("Harness cutover confirmation returned an invalid payload");
  return payload;
}

export async function acceptTutorFirstTurn(input: {
  userId: string;
  content: string;
  clientActionId: string;
}): Promise<TutorInputAcceptedResponse> {
  const payload = await requestJson(`${API_BASE_URL}/api/tutor/conversations/first-turn`, {
    method: "POST",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({ user_id: input.userId, content: input.content, client_action_id: input.clientActionId }),
  });
  const response = toTutorInputAcceptedResponse(payload);
  if (!response) throw new Error("Tutor first-turn API returned an invalid payload");
  return response;
}

export async function fetchTutorConversations(input: {
  userId: string;
  limit?: number;
  cursor?: string | null;
  signal?: AbortSignal;
}): Promise<TutorConversationListResponse> {
  const query = new URLSearchParams({ user_id: input.userId, limit: String(input.limit ?? 8) });
  if (input.cursor) query.set("cursor", input.cursor);
  const payload = await requestJson(`${API_BASE_URL}/api/tutor/conversations?${query.toString()}`, { signal: input.signal });
  const response = toTutorConversationListResponse(payload);
  if (!response) throw new Error("Tutor conversation-list API returned an invalid payload");
  return response;
}

export async function fetchTutorConversationHistory(input: {
  userId: string;
  conversationId: string;
  limit?: number;
  cursor?: string | null;
  signal?: AbortSignal;
}): Promise<TutorConversationHistoryResponse> {
  const query = new URLSearchParams({ user_id: input.userId, limit: String(input.limit ?? 40) });
  if (input.cursor) query.set("cursor", input.cursor);
  const payload = await requestJson(
    `${API_BASE_URL}/api/tutor/conversations/${encodeURIComponent(input.conversationId)}/history?${query.toString()}`,
    { signal: input.signal },
  );
  const response = toTutorConversationHistoryResponse(payload);
  if (!response) throw new Error("Tutor history API returned an invalid payload");
  return response;
}

export async function acceptTutorConversationInput(input: {
  userId: string;
  conversationId: string;
  content: string;
  clientActionId: string;
}): Promise<TutorInputAcceptedResponse> {
  const payload = await requestJson(
    `${API_BASE_URL}/api/tutor/conversations/${encodeURIComponent(input.conversationId)}/inputs`,
    {
      method: "POST",
      headers: tutorMutationHeaders(input.clientActionId),
      body: JSON.stringify({ user_id: input.userId, content: input.content, client_action_id: input.clientActionId }),
    },
  );
  const response = toTutorInputAcceptedResponse(payload);
  if (!response) throw new Error("Tutor input API returned an invalid payload");
  return response;
}

export async function acceptTutorRunInput(input: {
  userId: string;
  runId: string;
  content: string;
  clientActionId: string;
}): Promise<TutorInputAcceptedResponse> {
  const payload = await requestJson(`${API_BASE_URL}/api/tutor/runs/${encodeURIComponent(input.runId)}/inputs`, {
    method: "POST",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({ user_id: input.userId, content: input.content, client_action_id: input.clientActionId }),
  });
  const response = toTutorInputAcceptedResponse(payload);
  if (!response) throw new Error("Tutor run-input API returned an invalid payload");
  return response;
}

export async function fetchTutorRun(userId: string, runId: string, signal?: AbortSignal): Promise<TutorRunState> {
  const query = new URLSearchParams({ user_id: userId });
  const payload = await requestJson(`${API_BASE_URL}/api/tutor/runs/${encodeURIComponent(runId)}?${query.toString()}`, { signal });
  const run = toTutorRunState(payload);
  if (!run) throw new Error("Tutor run API returned an invalid payload");
  return run;
}

export async function fetchTutorActivity(userId: string, signal?: AbortSignal): Promise<TutorActivityItem[]> {
  const payload = await requestJson(`${API_BASE_URL}/api/tutor/activity?${new URLSearchParams({ user_id: userId }).toString()}`, { signal });
  if (!isRecord(payload) || !Array.isArray(payload.items)) throw new Error("Tutor activity API returned an invalid payload");
  const items = payload.items.map(toTutorActivityItem);
  if (items.some((item) => item === null)) throw new Error("Tutor activity API returned an invalid item");
  return items.filter((item): item is TutorActivityItem => item !== null);
}

export async function fetchTutorInbox(userId: string, signal?: AbortSignal): Promise<TutorInboxItem[]> {
  const payload = await requestJson(`${API_BASE_URL}/api/tutor/inbox?${new URLSearchParams({ user_id: userId }).toString()}`, { signal });
  if (!isRecord(payload) || !Array.isArray(payload.items)) throw new Error("Tutor inbox API returned an invalid payload");
  const items = payload.items.map(toTutorInboxItem);
  if (items.some((item) => item === null)) throw new Error("Tutor inbox API returned an invalid item");
  return items.filter((item): item is TutorInboxItem => item !== null);
}

export async function markTutorInboxRead(input: { userId: string; inboxId: string; clientActionId: string }): Promise<TutorInboxItem> {
  const payload = await requestJson(`${API_BASE_URL}/api/tutor/inbox/${encodeURIComponent(input.inboxId)}/read`, {
    method: "POST",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({ user_id: input.userId, client_action_id: input.clientActionId }),
  });
  const item = isRecord(payload) ? toTutorInboxItem(payload.inbox) : null;
  if (!item) throw new Error("Tutor inbox-read API returned an invalid payload");
  return item;
}

export async function dismissTutorInbox(input: { userId: string; inboxId: string; clientActionId: string }): Promise<TutorInboxItem> {
  const payload = await requestJson(`${API_BASE_URL}/api/tutor/inbox/${encodeURIComponent(input.inboxId)}/dismiss`, {
    method: "POST",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({ user_id: input.userId, client_action_id: input.clientActionId }),
  });
  const item = isRecord(payload) ? toTutorInboxItem(payload.inbox) : null;
  if (!item) throw new Error("Tutor inbox-dismiss API returned an invalid payload");
  return item;
}

export async function fetchTutorMemory(userId: string, signal?: AbortSignal): Promise<TutorMemoryItem[]> {
  const payload = await requestJson(`${API_BASE_URL}/api/tutor/memory?${new URLSearchParams({ user_id: userId }).toString()}`, { signal });
  if (!isRecord(payload) || !Array.isArray(payload.items)) throw new Error("Tutor memory API returned an invalid payload");
  const items = payload.items.map(toTutorMemoryItem);
  if (items.some((item) => item === null)) throw new Error("Tutor memory API returned an invalid item");
  return items.filter((item): item is TutorMemoryItem => item !== null);
}

export async function correctTutorMemory(input: {
  userId: string;
  entryId: string;
  statement: string;
  clientActionId: string;
}): Promise<TutorMemoryItem> {
  const payload = await requestJson(`${API_BASE_URL}/api/tutor/memory/${encodeURIComponent(input.entryId)}`, {
    method: "PATCH",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({
      user_id: input.userId,
      statement: input.statement,
      client_action_id: input.clientActionId,
    }),
  });
  const item = isRecord(payload) ? toTutorMemoryItem(payload.memory) : null;
  if (!item) throw new Error("Tutor memory-correction API returned an invalid payload");
  return item;
}

export async function deleteTutorMemory(input: { userId: string; entryId: string; clientActionId: string }): Promise<void> {
  const payload = await requestJson(`${API_BASE_URL}/api/tutor/memory/${encodeURIComponent(input.entryId)}`, {
    method: "DELETE",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({ user_id: input.userId, client_action_id: input.clientActionId }),
  });
  if (!isRecord(payload) || payload.entry_id !== input.entryId || payload.state !== "deleted") {
    throw new Error("Tutor memory-delete API returned an invalid payload");
  }
}

export async function fetchTutorPlanRevisions(userId: string, signal?: AbortSignal): Promise<TutorPlanRevisionList> {
  const payload = await requestJson(`${API_BASE_URL}/api/tutor/plans/revisions?${new URLSearchParams({ user_id: userId }).toString()}`, { signal });
  const response = toTutorPlanRevisionList(payload);
  if (!response) throw new Error("Tutor plan-revision API returned an invalid payload");
  return response;
}

export async function rollbackTutorPlan(input: { userId: string; clientActionId: string }): Promise<TutorPlanRevision | null> {
  const payload = await requestJson(`${API_BASE_URL}/api/tutor/plans/rollback`, {
    method: "POST",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({ user_id: input.userId, client_action_id: input.clientActionId }),
  });
  if (!isRecord(payload)) throw new Error("Tutor plan-rollback API returned an invalid payload");
  if (payload.active_plan === null) return null;
  const plan = toTutorPlanRevision(payload.active_plan);
  if (!plan) throw new Error("Tutor plan-rollback API returned an invalid plan");
  return plan;
}

export async function fetchTutorPreferences(userId: string, signal?: AbortSignal): Promise<TutorPreferences> {
  const payload = await requestJson(`${API_BASE_URL}/api/tutor/preferences?${new URLSearchParams({ user_id: userId }).toString()}`, { signal });
  const preferences = toTutorPreferences(payload);
  if (!preferences) throw new Error("Tutor preferences API returned an invalid payload");
  return preferences;
}

export async function updateTutorPreferences(input: {
  userId: string;
  clientActionId: string;
  inferredMemoryEnabled?: boolean;
  expectedMemorySettingVersion?: string;
  proactivePaused?: boolean;
}): Promise<TutorPreferences> {
  const payload = await requestJson(`${API_BASE_URL}/api/tutor/preferences`, {
    method: "PATCH",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({
      user_id: input.userId,
      client_action_id: input.clientActionId,
      ...(input.inferredMemoryEnabled === undefined ? {} : { inferred_memory_enabled: input.inferredMemoryEnabled }),
      ...(input.expectedMemorySettingVersion ? { expected_memory_setting_version: input.expectedMemorySettingVersion } : {}),
      ...(input.proactivePaused === undefined ? {} : { proactive_paused: input.proactivePaused }),
    }),
  });
  const preferences = toTutorPreferences(payload);
  if (!preferences) throw new Error("Tutor preferences-update API returned an invalid payload");
  return preferences;
}

export function buildTutorRunEventsUrl(runId: string, userId: string): string {
  const url = new URL(`/api/tutor/runs/${encodeURIComponent(runId)}/events`, API_BASE_URL);
  url.searchParams.set("user_id", userId);
  return url.toString();
}

function tutorMutationHeaders(clientActionId: string): Record<string, string> {
  return { "Idempotency-Key": clientActionId };
}

async function requestJson(url: string, init: RequestInit = {}): Promise<unknown> {
  const response = await fetch(url, {
    ...init,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-Request-Id": `desktop-${Date.now()}`,
      ...init.headers,
    },
  });
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    if (!response.ok) throw new Error(`API request failed with status ${response.status}`);
    throw new Error("API response was not JSON");
  }
  if (!response.ok) {
    if (isRecord(payload) && isApiError(payload.error)) throw new ApiRequestError(payload.error);
    throw new Error(`API request failed with status ${response.status}`);
  }
  return payload;
}

function isApiHealth(payload: unknown): payload is ApiHealth {
  return isRecord(payload) && payload.status === "ok" && isString(payload.service);
}

function toLanguageCourse(payload: unknown): LanguageCourse | null {
  if (!isRecord(payload) || !isString(payload.id) || !isString(payload.title) || !isString(payload.language)) return null;
  return { id: payload.id, title: payload.title, language: payload.language };
}

function isUserProfile(payload: unknown): payload is UserProfile {
  return (
    isRecord(payload) &&
    isString(payload.id) &&
    isString(payload.display_name) &&
    isNullableString(payload.learning_style) &&
    isNullableString(payload.teaching_preference) &&
    isNullableString(payload.encouragement_preference) &&
    isNullableString(payload.profession) &&
    isNullableString(payload.background_context) &&
    Array.isArray(payload.preferred_time_slots) &&
    payload.preferred_time_slots.every(isRecord) &&
    isRecord(payload.reminder_preference) &&
    isString(payload.created_at) &&
    isString(payload.updated_at)
  );
}

function isHarnessCutoverDecision(payload: unknown): payload is HarnessCutoverDecision {
  if (!isRecord(payload) || !isString(payload.cutover_version) || payload.rollout_active !== true) return false;
  if (!isHarnessCutoverState(payload.state) || !isHarnessCutoverNextAction(payload.next_action)) return false;
  if (payload.summary !== undefined && !isHarnessCutoverSummary(payload.summary)) return false;
  if (payload.summary_version !== undefined && !isNonNegativeSafeInteger(payload.summary_version)) return false;
  if (payload.preview_nonce !== undefined && !isString(payload.preview_nonce)) return false;
  if (payload.summary_hash !== undefined && !isString(payload.summary_hash)) return false;
  if (payload.code !== undefined && !isString(payload.code)) return false;
  if (payload.verified_at !== undefined && !isNullableString(payload.verified_at)) return false;
  if (payload.idempotent_replayed !== undefined && typeof payload.idempotent_replayed !== "boolean") return false;
  return true;
}

function isHarnessCutoverState(value: unknown): value is HarnessCutoverDecision["state"] {
  return value === "summary_ready" || value === "verified" || value === "blocked_target_state" || value === "blocked_checkpoint_scope";
}

function isHarnessCutoverNextAction(value: unknown): value is HarnessCutoverDecision["next_action"] {
  return value === "confirm_cutover" || value === "enter_tutor" || value === "resolve_cutover_block";
}

function isHarnessCutoverSummary(payload: unknown): boolean {
  return (
    isRecord(payload) &&
    Array.isArray(payload.legacy_categories) &&
    payload.legacy_categories.every((item) => isRecord(item) && isString(item.id) && typeof item.count === "number") &&
    Array.isArray(payload.legacy_profile_fields) &&
    payload.legacy_profile_fields.every((item) => isRecord(item) && isString(item.id) && item.will_clear === true) &&
    isRecord(payload.checkpoint) &&
    (payload.checkpoint.state === "not_configured" || payload.checkpoint.state === "scoped" || payload.checkpoint.state === "unresolved") &&
    typeof payload.checkpoint.record_count === "number" &&
    Array.isArray(payload.retained_categories) &&
    payload.retained_categories.every(isString) &&
    typeof payload.target_state_present === "boolean"
  );
}

function toTutorConversationListResponse(payload: unknown): TutorConversationListResponse | null {
  if (!isRecord(payload) || !Array.isArray(payload.items) || !isNullableString(payload.next_cursor) || typeof payload.has_more !== "boolean") return null;
  const items: TutorConversationSummary[] = [];
  for (const item of payload.items) {
    const parsed = toTutorConversationSummary(item);
    if (!parsed) return null;
    items.push(parsed);
  }
  return { items, next_cursor: payload.next_cursor, has_more: payload.has_more };
}

function toTutorConversationHistoryResponse(payload: unknown): TutorConversationHistoryResponse | null {
  if (!isRecord(payload) || !Array.isArray(payload.items) || !isNullableString(payload.next_cursor) || typeof payload.has_more !== "boolean") return null;
  if (!("active_run" in payload)) return null;
  const activeRun = payload.active_run === null ? null : toTutorForegroundRun(payload.active_run);
  if (activeRun === null && payload.active_run !== null) return null;
  const items: TutorHistoryItem[] = [];
  for (const item of payload.items) {
    const parsed = toTutorHistoryItem(item);
    if (!parsed) return null;
    items.push(parsed);
  }
  return { items, next_cursor: payload.next_cursor, has_more: payload.has_more, active_run: activeRun };
}

function toTutorConversationSummary(payload: unknown): TutorConversationSummary | null {
  if (!isRecord(payload) || !isString(payload.conversation_id) || !isString(payload.title) || !isNullableString(payload.last_public_activity_at)) return null;
  if (!("active_run" in payload)) return null;
  const activeRun = payload.active_run === null ? null : toTutorForegroundRun(payload.active_run);
  if (activeRun === null && payload.active_run !== null) return null;
  return {
    conversation_id: payload.conversation_id,
    title: payload.title,
    last_public_activity_at: payload.last_public_activity_at,
    active_run: activeRun,
  };
}

function toTutorForegroundRun(payload: unknown): TutorForegroundRun | null {
  if (!isRecord(payload) || !isString(payload.run_id) || !isTutorRunStatus(payload.status) || !isNullableTutorContinuationKind(payload.continuation_kind)) return null;
  return { run_id: payload.run_id, status: payload.status, continuation_kind: payload.continuation_kind };
}

function toTutorHistoryItem(payload: unknown): TutorHistoryItem | null {
  if (!isRecord(payload) || !isString(payload.kind) || !isString(payload.id) || !isNullableString(payload.created_at)) return null;
  if (payload.kind === "message") {
    if ((payload.role !== "learner" && payload.role !== "tutor") || !isString(payload.content)) return null;
    return { kind: "message", id: payload.id, role: payload.role, content: payload.content, created_at: payload.created_at };
  }
  if (payload.kind === "process") {
    return toTutorPublicProcess(payload);
  }
  return null;
}

function toTutorPublicProcess(payload: unknown): TutorPublicProcess | null {
  if (!isRecord(payload) || payload.kind !== "process" || !isString(payload.id) || !isString(payload.run_id) || !isTutorProcessDisplayState(payload.display_state) || !Array.isArray(payload.steps) || !isNonNegativeSafeInteger(payload.elapsed_seconds) || !isNullableString(payload.created_at) || !isNullableString(payload.finished_at)) return null;
  const steps: TutorPublicProcessStep[] = [];
  for (const step of payload.steps) {
    const parsed = toTutorPublicProcessStep(step);
    if (!parsed) return null;
    steps.push(parsed);
  }
  return {
    kind: "process",
    id: payload.id,
    run_id: payload.run_id,
    display_state: payload.display_state,
    steps,
    elapsed_seconds: payload.elapsed_seconds,
    created_at: payload.created_at,
    finished_at: payload.finished_at,
  };
}

function toTutorPublicProcessStep(payload: unknown): TutorPublicProcessStep | null {
  if (!isRecord(payload) || !isTutorProcessStepKey(payload.key) || !isTutorProcessStepState(payload.state) || !isString(payload.label)) return null;
  return { key: payload.key, state: payload.state, label: payload.label };
}

function toTutorInputAcceptedResponse(payload: unknown): TutorInputAcceptedResponse | null {
  if (!isRecord(payload) || !isString(payload.conversation_id) || !isString(payload.run_id) || !isNonNegativeSafeInteger(payload.input_revision) || !isString(payload.message_id) || !isNonNegativeSafeInteger(payload.event_cursor) || typeof payload.merged !== "boolean" || typeof payload.input_replayed !== "boolean" || typeof payload.idempotent_replayed !== "boolean" || !("process" in payload) || !("replaced_run_id" in payload) || !("replaced_process" in payload)) return null;
  const run = toTutorRunState(payload.run);
  const process = payload.process === null ? null : toTutorPublicProcess(payload.process);
  const replacedProcess = payload.replaced_process === null ? null : toTutorPublicProcess(payload.replaced_process);
  if (!run || (process === null && payload.process !== null) || (replacedProcess === null && payload.replaced_process !== null) || !isNullableString(payload.replaced_run_id)) return null;
  return {
    conversation_id: payload.conversation_id,
    run_id: payload.run_id,
    input_revision: payload.input_revision,
    message_id: payload.message_id,
    event_cursor: payload.event_cursor,
    merged: payload.merged,
    input_replayed: payload.input_replayed,
    idempotent_replayed: payload.idempotent_replayed,
    run,
    process,
    replaced_run_id: payload.replaced_run_id,
    replaced_process: replacedProcess,
  };
}

function toTutorRunState(payload: unknown): TutorRunState | null {
  if (!isRecord(payload) || !isString(payload.run_id) || !isString(payload.conversation_id) || (payload.origin !== "interactive" && payload.origin !== "proactive") || !isTutorRunStatus(payload.status) || !isNonNegativeSafeInteger(payload.input_revision) || typeof payload.cancelled !== "boolean" || !isNonNegativeSafeInteger(payload.iteration_count) || !isNonNegativeSafeInteger(payload.model_call_count) || !isNonNegativeSafeInteger(payload.capability_call_count) || !isNonNegativeSafeInteger(payload.effect_count) || !isNullableTutorTerminalOutcome(payload.terminal_outcome) || !isNullableTutorContinuationKind(payload.continuation_kind) || !isNullableString(payload.created_at) || !isNullableString(payload.updated_at)) return null;
  return {
    run_id: payload.run_id,
    conversation_id: payload.conversation_id,
    origin: payload.origin,
    status: payload.status,
    input_revision: payload.input_revision,
    cancelled: payload.cancelled,
    iteration_count: payload.iteration_count,
    model_call_count: payload.model_call_count,
    capability_call_count: payload.capability_call_count,
    effect_count: payload.effect_count,
    terminal_outcome: payload.terminal_outcome,
    continuation_kind: payload.continuation_kind,
    created_at: payload.created_at,
    updated_at: payload.updated_at,
  };
}

function toTutorActivityItem(payload: unknown): TutorActivityItem | null {
  if (!isRecord(payload) || !isString(payload.activity_id) || !isString(payload.category) || !isString(payload.reason) || !isStringArray(payload.evidence) || !isNullableString(payload.created_at)) return null;
  return { activity_id: payload.activity_id, category: payload.category, reason: payload.reason, evidence: payload.evidence, created_at: payload.created_at };
}

function toTutorInboxItem(payload: unknown): TutorInboxItem | null {
  if (!isRecord(payload) || !isString(payload.inbox_id) || !isString(payload.activity_id) || !isString(payload.message) || !isTutorInboxState(payload.state) || !isNullableString(payload.read_at) || !isNullableString(payload.dismissed_at) || !isNullableString(payload.created_at)) return null;
  return { inbox_id: payload.inbox_id, activity_id: payload.activity_id, message: payload.message, state: payload.state, read_at: payload.read_at, dismissed_at: payload.dismissed_at, created_at: payload.created_at };
}

function toTutorMemoryItem(payload: unknown): TutorMemoryItem | null {
  if (!isRecord(payload) || !isString(payload.entry_id) || (payload.memory_kind !== "objective_fact" && payload.memory_kind !== "inference") || !isTutorMemoryState(payload.state) || !isString(payload.category) || !isString(payload.statement) || !isNullableString(payload.confidence) || !isString(payload.provenance) || !isNullableString(payload.replaced_entry_id) || !isStringArray(payload.evidence) || !isNullableString(payload.retention_until) || !isNullableString(payload.stale_after) || !isNullableString(payload.created_at)) return null;
  return {
    entry_id: payload.entry_id,
    memory_kind: payload.memory_kind,
    state: payload.state,
    category: payload.category,
    statement: payload.statement,
    confidence: payload.confidence,
    provenance: payload.provenance,
    replaced_entry_id: payload.replaced_entry_id,
    evidence: payload.evidence,
    retention_until: payload.retention_until,
    stale_after: payload.stale_after,
    created_at: payload.created_at,
  };
}

function toTutorPlanRevision(payload: unknown): TutorPlanRevision | null {
  if (!isRecord(payload) || !isString(payload.revision_id) || !isNullableString(payload.predecessor_revision_id) || !isString(payload.title) || !isStringArray(payload.outline) || !isStringArray(payload.diff) || !isString(payload.learner_reason) || !isStringArray(payload.evidence) || !isNullableString(payload.created_at)) return null;
  return {
    revision_id: payload.revision_id,
    predecessor_revision_id: payload.predecessor_revision_id,
    title: payload.title,
    outline: payload.outline,
    diff: payload.diff,
    learner_reason: payload.learner_reason,
    evidence: payload.evidence,
    created_at: payload.created_at,
  };
}

function toTutorPlanRevisionList(payload: unknown): TutorPlanRevisionList | null {
  if (!isRecord(payload) || !isNullableString(payload.active_revision_id) || !Array.isArray(payload.items)) return null;
  const items = payload.items.map(toTutorPlanRevision);
  if (items.some((item) => item === null)) return null;
  return { active_revision_id: payload.active_revision_id, items: items.filter((item): item is TutorPlanRevision => item !== null) };
}

function toTutorPreferences(payload: unknown): TutorPreferences | null {
  if (!isRecord(payload) || typeof payload.inferred_memory_enabled !== "boolean" || !isString(payload.memory_setting_version) || typeof payload.proactive_paused !== "boolean" || typeof payload.proactive_enabled !== "boolean") return null;
  return {
    inferred_memory_enabled: payload.inferred_memory_enabled,
    memory_setting_version: payload.memory_setting_version,
    proactive_paused: payload.proactive_paused,
    proactive_enabled: payload.proactive_enabled,
  };
}

function isTutorRunStatus(value: unknown): value is TutorRunState["status"] {
  return value === "queued" || value === "leased" || value === "running" || value === "waiting_for_input" || value === "waiting_for_capability" || value === "awaiting_effect_commit" || value === "completed" || value === "model_unavailable" || value === "blocked_policy" || value === "budget_exhausted" || value === "cancelled" || value === "failed";
}

function isNullableTutorTerminalOutcome(value: unknown): value is TutorRunState["terminal_outcome"] {
  return value === null || value === "completed" || value === "model_unavailable" || value === "blocked_policy" || value === "budget_exhausted" || value === "cancelled" || value === "failed";
}

function isNullableTutorContinuationKind(value: unknown): value is TutorContinuationKind | null {
  return value === null || value === "approval" || value === "capability_result" || value === "external_result";
}

function isTutorProcessDisplayState(value: unknown): value is TutorPublicProcess["display_state"] {
  return value === "thinking" || value === "completed" || value === "superseded" || value === "unavailable";
}

function isTutorProcessStepKey(value: unknown): value is TutorPublicProcessStep["key"] {
  return value === "input_received" || value === "context_prepared" || value === "authorized_resource_checked" || value === "learning_reply_generated" || value === "replaced_by_newer_input";
}

function isTutorProcessStepState(value: unknown): value is TutorPublicProcessStep["state"] {
  return value === "completed" || value === "current";
}

function isTutorInboxState(value: unknown): value is TutorInboxItem["state"] {
  return value === "unread" || value === "read" || value === "dismissed";
}

function isTutorMemoryState(value: unknown): value is TutorMemoryItem["state"] {
  return value === "active" || value === "replaced" || value === "deleted";
}

function isApiError(value: unknown): value is ApiError {
  return isRecord(value) && isString(value.code) && isString(value.message) && isRecord(value.details) && isString(value.request_id) && typeof value.recoverable === "boolean";
}

function isNullableString(value: unknown): value is string | null {
  return isString(value) || value === null;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isString);
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isNonNegativeSafeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
