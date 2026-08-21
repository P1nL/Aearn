import {
  ApiRequestError,
  type ApiError,
  type ApiHealth,
  type HarnessCutoverDecision,
  type TutorThreadTurnV2Capability,
  type LanguageCourse,
  type LessonAssignment,
  type LessonAuthoringRun,
  type LessonBlock,
  type LessonCitation,
  type LessonDocument,
  type LessonDocumentState,
  type LessonGateAction,
  type LessonGateExercise,
  type LessonGateHint,
  type LessonGateItem,
  type LessonGateList,
  type LessonGatePrepareResponse,
  type LessonGateResult,
  type LessonPrepareResponse,
  type ModelCodeReviewSubmission,
  type ModelReviewArtifact,
  type ModelReviewAuthoringRun,
  type ModelReviewEvidenceResponse,
  type ModelReviewFindingFeedback,
  type ModelReviewPrompt,
  type ModelReviewSafeFeedback,
  type ModelReviewScoreBreakdown,
  type ModelReviewVisibleEvidence,
  type LessonUpdateProposal,
  type ExerciseAttemptState,
  type ExerciseAttemptOutcome,
  type ExecutionTier,
  type ModuleDiagnosticImpact,
  type ModuleDiagnosticItem,
  type ModuleDiagnosticState,
  type LearningLanguageCatalogItem,
  type LearningPlanDraft,
  type LearningPlanModule,
  type LearningPlanNode,
  type LearningPlanProfile,
  type LearningPlanSession,
  type LearningScopeInput,
  type LearningTrackSummary,
  type LearningTrackDetail,
  type LearningRoadmap,
  type LearningRoadmapModule,
  type LearningRoadmapNode,
  type TutorActivityItem,
  type TutorContinuationKind,
  type TutorConversationHistoryResponse,
  type TutorConversationResponse,
  type TutorConversationSnapshotResponse,
  type TutorConversationInputResponse,
  type TutorControlledTurnResponse,
  type TutorContextReference,
  type TutorContextReferenceDraft,
  type TutorConversationListResponse,
  type TutorConversationSummary,
  type TutorForegroundRun,
  type TutorHistoryItem,
  type TutorInboxItem,
  type TutorInteractionRequestItem,
  type TutorInteractionResponseAccepted,
  type TutorInteractionResponseDraft,
  type TutorRequestPresentation,
  type TutorInputAcceptedResponse,
  type TutorMemoryItem,
  type TutorPlanRevision,
  type TutorPlanRevisionList,
  type TutorPreferences,
  type TutorPublicProcess,
  type TutorPublicProcessStep,
  type TutorQueuedInput,
  type TutorQueueResumeResponse,
  type TutorQueueStateResponse,
  type TutorQueueSteerResponse,
  type TutorRunState,
  type ReviewAttempt,
  type ReviewHint,
  type ReviewQueue,
  type ReviewQueueItem,
  type ReviewSession,
  type ReviewSessionAttemptSummary,
  type ReviewSessionItem,
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

export async function fetchTutorThreadTurnV2Capability(
  userId: string,
  signal?: AbortSignal,
): Promise<TutorThreadTurnV2Capability> {
  const payload = await requestJson(`${API_BASE_URL}/api/tutor/capabilities/thread-turn-v2?user_id=${encodeURIComponent(userId)}`, { signal });
  const parsed = parseTutorThreadTurnV2Capability(payload);
  if (!parsed) throw new Error("Tutor thread/turn v2 capability API returned an invalid payload");
  return parsed;
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
  learningScope?: LearningScopeInput;
  contextReferences?: TutorContextReferenceDraft[];
}): Promise<TutorInputAcceptedResponse> {
  const payload = await requestJson(`${API_BASE_URL}/api/tutor/conversations/first-turn`, {
    method: "POST",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({
      user_id: input.userId,
      content: input.content,
      client_action_id: input.clientActionId,
      ...(input.learningScope ? { learning_scope: input.learningScope } : {}),
      ...(input.contextReferences ? { context_references: input.contextReferences } : {}),
    }),
  });
  const response = toTutorInputAcceptedResponse(payload);
  if (!response) throw new Error("Tutor first-turn API returned an invalid payload");
  return response;
}

export async function createOrResumeTutorConversation(input: {
  userId: string;
  clientActionId: string;
  conversationId?: string | null;
  learningScope?: LearningScopeInput;
}): Promise<TutorConversationResponse> {
  const payload = await requestJson(`${API_BASE_URL}/api/tutor/conversations`, {
    method: "POST",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({
      user_id: input.userId,
      client_action_id: input.clientActionId,
      ...(input.conversationId ? { conversation_id: input.conversationId } : {}),
      ...(input.learningScope ? { learning_scope: input.learningScope } : {}),
    }),
  });
  const response = toTutorConversationResponse(payload);
  if (!response) throw new Error("Tutor conversation API returned an invalid payload");
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

export async function fetchTutorConversationSnapshot(input: {
  userId: string;
  conversationId: string;
  limit?: number;
  cursor?: string | null;
  signal?: AbortSignal;
}): Promise<TutorConversationSnapshotResponse> {
  const query = new URLSearchParams({ user_id: input.userId, limit: String(input.limit ?? 40) });
  if (input.cursor) query.set("cursor", input.cursor);
  const payload = await requestJson(
    `${API_BASE_URL}/api/tutor/conversations/${encodeURIComponent(input.conversationId)}/snapshot?${query.toString()}`,
    { signal: input.signal },
  );
  const response = toTutorConversationSnapshotResponse(payload);
  if (!response) throw new Error("Tutor snapshot API returned an invalid payload");
  return response;
}

export async function respondToTutorInteractionRequest(input: {
  userId: string;
  conversationId: string;
  itemId: string;
  expectedRequestVersion: number;
  response: TutorInteractionResponseDraft;
  clientActionId: string;
}): Promise<TutorInteractionResponseAccepted> {
  const payload = await requestJson(
    `${API_BASE_URL}/api/tutor/conversations/${encodeURIComponent(input.conversationId)}/requests/${encodeURIComponent(input.itemId)}/responses`,
    {
      method: "POST",
      headers: tutorMutationHeaders(input.clientActionId),
      body: JSON.stringify({
        user_id: input.userId,
        client_action_id: input.clientActionId,
        expected_request_version: input.expectedRequestVersion,
        response: input.response,
      }),
    },
  );
  const response = toTutorInteractionResponseAccepted(payload);
  if (!response) throw new Error("Tutor request-response API returned an invalid payload");
  return response;
}

export async function acceptTutorConversationInput(input: {
  userId: string;
  conversationId: string;
  content: string;
  clientActionId: string;
  learningScope?: LearningScopeInput;
  contextReferences?: TutorContextReferenceDraft[];
}): Promise<TutorConversationInputResponse> {
  const payload = await requestJson(
    `${API_BASE_URL}/api/tutor/conversations/${encodeURIComponent(input.conversationId)}/inputs`,
    {
      method: "POST",
      headers: tutorMutationHeaders(input.clientActionId),
      body: JSON.stringify({
        user_id: input.userId,
        content: input.content,
        client_action_id: input.clientActionId,
        ...(input.learningScope ? { learning_scope: input.learningScope } : {}),
        ...(input.contextReferences ? { context_references: input.contextReferences } : {}),
      }),
    },
  );
  const response = toTutorConversationInputResponse(payload);
  if (!response) throw new Error("Tutor input API returned an invalid payload");
  return response;
}

export async function fetchTutorQueue(input: {
  userId: string;
  conversationId: string;
  signal?: AbortSignal;
}): Promise<TutorQueueStateResponse> {
  const query = new URLSearchParams({ user_id: input.userId });
  const payload = await requestJson(
    `${API_BASE_URL}/api/tutor/conversations/${encodeURIComponent(input.conversationId)}/queue?${query.toString()}`,
    { signal: input.signal },
  );
  const response = toTutorQueueStateResponse(payload);
  if (!response) throw new Error("Tutor queue API returned an invalid payload");
  return response;
}

export async function editTutorQueueItem(input: {
  userId: string; conversationId: string; itemId: string; content: string;
  expectedControlVersion: number; expectedItemVersion: number; clientActionId: string;
}): Promise<TutorQueueStateResponse & { queue_item: TutorQueuedInput }> {
  const payload = await requestJson(
    `${API_BASE_URL}/api/tutor/conversations/${encodeURIComponent(input.conversationId)}/queue/${encodeURIComponent(input.itemId)}`,
    { method: "PATCH", headers: tutorMutationHeaders(input.clientActionId), body: JSON.stringify({
      user_id: input.userId, client_action_id: input.clientActionId, content: input.content,
      expected_control_version: input.expectedControlVersion, expected_item_version: input.expectedItemVersion,
    }) },
  );
  const response = toTutorQueueMutationResponse(payload);
  if (!response?.queue_item) throw new Error("Tutor queue-edit API returned an invalid payload");
  return { ...response.state, queue_item: response.queue_item };
}

export async function deleteTutorQueueItem(input: {
  userId: string; conversationId: string; itemId: string;
  expectedControlVersion: number; expectedItemVersion: number; clientActionId: string;
}): Promise<TutorQueueStateResponse> {
  const payload = await requestJson(
    `${API_BASE_URL}/api/tutor/conversations/${encodeURIComponent(input.conversationId)}/queue/${encodeURIComponent(input.itemId)}`,
    { method: "DELETE", headers: tutorMutationHeaders(input.clientActionId), body: JSON.stringify({
      user_id: input.userId, client_action_id: input.clientActionId,
      expected_control_version: input.expectedControlVersion, expected_item_version: input.expectedItemVersion,
    }) },
  );
  const response = toTutorQueueStateResponse(payload);
  if (!response) throw new Error("Tutor queue-delete API returned an invalid payload");
  return response;
}

export async function reorderTutorQueue(input: {
  userId: string; conversationId: string; itemIds: string[];
  expectedControlVersion: number; clientActionId: string;
}): Promise<TutorQueueStateResponse> {
  const payload = await requestJson(
    `${API_BASE_URL}/api/tutor/conversations/${encodeURIComponent(input.conversationId)}/queue/reorder`,
    { method: "POST", headers: tutorMutationHeaders(input.clientActionId), body: JSON.stringify({
      user_id: input.userId, client_action_id: input.clientActionId, item_ids: input.itemIds,
      expected_control_version: input.expectedControlVersion,
    }) },
  );
  const response = toTutorQueueStateResponse(payload);
  if (!response) throw new Error("Tutor queue-reorder API returned an invalid payload");
  return response;
}

export async function interruptTutorTurn(input: {
  userId: string; conversationId: string; expectedTurnId: string; expectedInputRevision: number;
  expectedControlVersion: number; clientActionId: string;
}): Promise<TutorQueueStateResponse> {
  const payload = await requestJson(
    `${API_BASE_URL}/api/tutor/conversations/${encodeURIComponent(input.conversationId)}/interrupt`,
    { method: "POST", headers: tutorMutationHeaders(input.clientActionId), body: JSON.stringify({
      user_id: input.userId, client_action_id: input.clientActionId,
      expected_control_version: input.expectedControlVersion, expected_turn_id: input.expectedTurnId,
      expected_input_revision: input.expectedInputRevision,
    }) },
  );
  const response = toTutorQueueStateResponse(payload);
  if (!response) throw new Error("Tutor interrupt API returned an invalid payload");
  return response;
}

export async function steerTutorQueueItem(input: {
  userId: string; conversationId: string; itemId: string; expectedTurnId: string;
  expectedInputRevision: number; expectedControlVersion: number; clientActionId: string;
}): Promise<TutorQueueSteerResponse> {
  const payload = await requestJson(
    `${API_BASE_URL}/api/tutor/conversations/${encodeURIComponent(input.conversationId)}/queue/${encodeURIComponent(input.itemId)}/steer`,
    { method: "POST", headers: tutorMutationHeaders(input.clientActionId), body: JSON.stringify({
      user_id: input.userId, client_action_id: input.clientActionId,
      expected_control_version: input.expectedControlVersion, expected_turn_id: input.expectedTurnId,
      expected_input_revision: input.expectedInputRevision,
    }) },
  );
  const response = toTutorControlledTurnResponse(payload, true);
  if (!response?.queue_item) throw new Error("Tutor queue-steer API returned an invalid payload");
  return { ...response.turn, queue_item: response.queue_item };
}

export async function resumeTutorQueue(input: {
  userId: string; conversationId: string; expectedControlVersion: number; clientActionId: string;
}): Promise<TutorQueueResumeResponse> {
  const payload = await requestJson(
    `${API_BASE_URL}/api/tutor/conversations/${encodeURIComponent(input.conversationId)}/queue/resume`,
    { method: "POST", headers: tutorMutationHeaders(input.clientActionId), body: JSON.stringify({
      user_id: input.userId, client_action_id: input.clientActionId,
      expected_control_version: input.expectedControlVersion,
    }) },
  );
  const turn = toTutorControlledTurnResponse(payload, false)?.turn;
  const state = toTutorQueueStateResponse(payload);
  if (!turn && !state) throw new Error("Tutor queue-resume API returned an invalid payload");
  return turn ?? state!;
}

export async function executeTutorQueueItem(input: {
  userId: string; conversationId: string; itemId: string;
  expectedControlVersion: number; clientActionId: string;
}): Promise<TutorControlledTurnResponse> {
  const payload = await requestJson(
    `${API_BASE_URL}/api/tutor/conversations/${encodeURIComponent(input.conversationId)}/queue/${encodeURIComponent(input.itemId)}/execute`,
    { method: "POST", headers: tutorMutationHeaders(input.clientActionId), body: JSON.stringify({
      user_id: input.userId, client_action_id: input.clientActionId,
      expected_control_version: input.expectedControlVersion,
    }) },
  );
  const response = toTutorControlledTurnResponse(payload, false)?.turn;
  if (!response) throw new Error("Tutor queue-execute API returned an invalid payload");
  return response;
}

export async function retryTutorTurn(input: {
  userId: string; conversationId: string; turnId: string;
  expectedControlVersion: number; clientActionId: string;
}): Promise<TutorControlledTurnResponse> {
  const payload = await requestJson(
    `${API_BASE_URL}/api/tutor/conversations/${encodeURIComponent(input.conversationId)}/turns/${encodeURIComponent(input.turnId)}/retry`,
    { method: "POST", headers: tutorMutationHeaders(input.clientActionId), body: JSON.stringify({
      user_id: input.userId, client_action_id: input.clientActionId,
      expected_control_version: input.expectedControlVersion,
    }) },
  );
  const response = toTutorControlledTurnResponse(payload, false)?.turn;
  if (!response) throw new Error("Tutor retry API returned an invalid payload");
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

export async function fetchLearningTracks(userId: string, signal?: AbortSignal): Promise<LearningTrackSummary[]> {
  const query = new URLSearchParams({ user_id: userId });
  const payload = await requestJson(`${API_BASE_URL}/api/learning-tracks?${query.toString()}`, { signal });
  if (!isRecord(payload) || !Array.isArray(payload.items)) throw new Error("LearningTrack API returned an invalid payload");
  const items = payload.items.map(toLearningTrackSummary);
  if (items.some((item) => item === null)) throw new Error("LearningTrack API returned an invalid item");
  return items.filter((item): item is LearningTrackSummary => item !== null);
}

export async function fetchLearningTrackDetail(
  userId: string,
  trackId: string,
  signal?: AbortSignal,
): Promise<LearningTrackDetail> {
  const query = new URLSearchParams({ user_id: userId });
  const payload = await requestJson(`${API_BASE_URL}/api/learning-tracks/${encodeURIComponent(trackId)}?${query.toString()}`, { signal });
  const track = isRecord(payload) && hasExactKeys(payload, ["track"]) ? toLearningTrackDetail(payload.track) : null;
  if (!track) throw new Error("LearningTrack detail API returned an invalid payload");
  return track;
}

export async function fetchLearningRoadmap(
  userId: string,
  trackId: string,
  signal?: AbortSignal,
): Promise<LearningRoadmap> {
  const query = new URLSearchParams({ user_id: userId });
  const payload = await requestJson(`${API_BASE_URL}/api/learning-tracks/${encodeURIComponent(trackId)}/roadmap?${query.toString()}`, { signal });
  const roadmap = isRecord(payload) && hasExactKeys(payload, ["roadmap"]) ? toLearningRoadmap(payload.roadmap) : null;
  if (!roadmap) throw new Error("Learning roadmap API returned an invalid payload");
  return roadmap;
}

export async function fetchReviewQueue(
  userId: string,
  trackId: string,
  signal?: AbortSignal,
): Promise<ReviewQueue> {
  const query = new URLSearchParams({ user_id: userId });
  const payload = await requestJson(`${API_BASE_URL}/api/learning-tracks/${encodeURIComponent(trackId)}/reviews?${query.toString()}`, { signal });
  const queue = toReviewQueue(payload);
  if (!queue) throw new Error("Review queue API returned an invalid payload");
  return queue;
}

export async function createReviewSession(input: {
  userId: string;
  trackId: string;
  knowledgeKey: string;
  expectedTrackVersion: number;
  expectedScheduleVersion: number;
  maxItems?: number;
  clientActionId: string;
}): Promise<ReviewSession> {
  const payload = await requestJson(`${API_BASE_URL}/api/learning-tracks/${encodeURIComponent(input.trackId)}/reviews/sessions`, {
    method: "POST",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({
      user_id: input.userId, client_action_id: input.clientActionId, knowledge_key: input.knowledgeKey,
      expected_track_version: input.expectedTrackVersion, expected_schedule_version: input.expectedScheduleVersion,
      max_items: input.maxItems ?? 1,
    }),
  });
  const session = toReviewSession(payload);
  if (!session) throw new Error("Review session API returned an invalid payload");
  return session;
}

export async function fetchReviewSession(
  userId: string, trackId: string, sessionId: string, signal?: AbortSignal,
): Promise<ReviewSession> {
  const query = new URLSearchParams({ user_id: userId });
  const payload = await requestJson(`${API_BASE_URL}/api/learning-tracks/${encodeURIComponent(trackId)}/reviews/sessions/${encodeURIComponent(sessionId)}?${query.toString()}`, { signal });
  const session = toReviewSession(payload);
  if (!session) throw new Error("Review session API returned an invalid payload");
  return session;
}

export async function recordReviewWarmup(input: {
  userId: string; trackId: string; sessionId: string; responseKind: "answered" | "skipped";
  confidence?: "low" | "medium" | "high"; expectedSessionVersion: number; clientActionId: string;
}): Promise<ReviewSession> {
  const payload = await requestJson(`${API_BASE_URL}/api/learning-tracks/${encodeURIComponent(input.trackId)}/reviews/sessions/${encodeURIComponent(input.sessionId)}/warmup`, {
    method: "POST", headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({ user_id: input.userId, client_action_id: input.clientActionId, response_kind: input.responseKind,
      ...(input.confidence ? { confidence: input.confidence } : {}), expected_session_version: input.expectedSessionVersion }),
  });
  const session = toReviewSession(payload);
  if (!session) throw new Error("Review warmup API returned an invalid payload");
  return session;
}

export async function requestReviewHint(input: {
  userId: string; trackId: string; sessionId: string; itemId: string; hintLevel: number;
  expectedSessionVersion: number; expectedItemVersion: number; clientActionId: string;
}): Promise<ReviewHint> {
  const payload = await requestJson(`${API_BASE_URL}/api/learning-tracks/${encodeURIComponent(input.trackId)}/reviews/sessions/${encodeURIComponent(input.sessionId)}/items/${encodeURIComponent(input.itemId)}/hints`, {
    method: "POST", headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({ user_id: input.userId, client_action_id: input.clientActionId, hint_level: input.hintLevel,
      expected_session_version: input.expectedSessionVersion, expected_item_version: input.expectedItemVersion }),
  });
  const hint = toReviewHint(payload);
  if (!hint) throw new Error("Review hint API returned an invalid payload");
  return hint;
}

type ReviewAttemptInput = {
  userId: string; trackId: string; sessionId: string; itemId: string; expectedSessionVersion: number;
  expectedItemVersion: number; clientActionId: string;
} & ({ submission: string; reviewSubmission?: never } | { submission?: never; reviewSubmission: ModelCodeReviewSubmission });

export async function createReviewAttempt(input: ReviewAttemptInput): Promise<ReviewAttempt> {
  const payload = await requestJson(`${API_BASE_URL}/api/learning-tracks/${encodeURIComponent(input.trackId)}/reviews/sessions/${encodeURIComponent(input.sessionId)}/items/${encodeURIComponent(input.itemId)}/attempts`, {
    method: "POST", headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({ user_id: input.userId, client_action_id: input.clientActionId,
      ...(input.reviewSubmission ? { review_submission: input.reviewSubmission } : { submission: input.submission }),
      expected_session_version: input.expectedSessionVersion, expected_item_version: input.expectedItemVersion }),
  });
  const attempt = toReviewAttempt(payload);
  if (!attempt) throw new Error("Review attempt API returned an invalid payload");
  return attempt;
}

export async function fetchReviewAttempt(
  userId: string, trackId: string, sessionId: string, attemptId: string, signal?: AbortSignal,
): Promise<ReviewAttempt> {
  const query = new URLSearchParams({ user_id: userId });
  const payload = await requestJson(`${API_BASE_URL}/api/learning-tracks/${encodeURIComponent(trackId)}/reviews/sessions/${encodeURIComponent(sessionId)}/attempts/${encodeURIComponent(attemptId)}?${query.toString()}`, { signal });
  const attempt = toReviewAttempt(payload);
  if (!attempt) throw new Error("Review attempt API returned an invalid payload");
  return attempt;
}

export async function finalizeReviewSession(input: {
  userId: string; trackId: string; sessionId: string; expectedSessionVersion: number; clientActionId: string;
}): Promise<ReviewSession> {
  const payload = await requestJson(`${API_BASE_URL}/api/learning-tracks/${encodeURIComponent(input.trackId)}/reviews/sessions/${encodeURIComponent(input.sessionId)}/finalize`, {
    method: "POST", headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({ user_id: input.userId, client_action_id: input.clientActionId, expected_session_version: input.expectedSessionVersion }),
  });
  const session = toReviewSession(payload);
  if (!session) throw new Error("Review finalization API returned an invalid payload");
  return session;
}

export async function fetchLearningLanguageCatalog(
  userId: string,
  signal?: AbortSignal,
): Promise<LearningLanguageCatalogItem[]> {
  const query = new URLSearchParams({ user_id: userId });
  const payload = await requestJson(`${API_BASE_URL}/api/learning-tracks/catalog?${query.toString()}`, { signal });
  if (!isRecord(payload) || !Array.isArray(payload.items)) throw new Error("Learning language catalog returned an invalid payload");
  const items = payload.items.map(toLearningLanguageCatalogItem);
  if (items.some((item) => item === null)) throw new Error("Learning language catalog returned an invalid item");
  return items.filter((item): item is LearningLanguageCatalogItem => item !== null);
}


export async function fetchLessonDocument(
  userId: string,
  trackId: string,
  knowledgeKey: string,
  signal?: AbortSignal,
): Promise<LessonDocumentState> {
  const query = new URLSearchParams({ user_id: userId });
  const url = API_BASE_URL + "/api/learning-tracks/" + encodeURIComponent(trackId) + "/lessons/" + encodeURIComponent(knowledgeKey) + "?" + query.toString();
  const payload = await requestJson(url, { signal });
  const state = toLessonDocumentState(payload);
  if (!state) throw new Error("LessonDocument API returned an invalid payload");
  return state;
}

export async function prepareLessonDocument(input: {
  userId: string;
  trackId: string;
  knowledgeKey: string;
  expectedTrackVersion: number;
  expectedProgressVersion: number;
  clientActionId: string;
  refresh?: boolean;
}): Promise<LessonPrepareResponse> {
  const operation = input.refresh ? "refresh" : "prepare";
  const url = API_BASE_URL + "/api/learning-tracks/" + encodeURIComponent(input.trackId) + "/lessons/" + encodeURIComponent(input.knowledgeKey) + "/" + operation;
  const payload = await requestJson(url, {
    method: "POST",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({
      user_id: input.userId,
      client_action_id: input.clientActionId,
      expected_track_version: input.expectedTrackVersion,
      expected_progress_version: input.expectedProgressVersion,
    }),
  });
  const response = toLessonPrepareResponse(payload);
  if (!response) throw new Error("Lesson prepare API returned an invalid payload");
  return response;
}

export async function startLessonDocument(input: {
  userId: string;
  trackId: string;
  knowledgeKey: string;
  assignmentId: string;
  expectedAssignmentVersion: number;
  expectedProgressVersion: number;
  clientActionId: string;
}): Promise<LessonAssignment> {
  const url = API_BASE_URL + "/api/learning-tracks/" + encodeURIComponent(input.trackId) + "/lessons/" + encodeURIComponent(input.knowledgeKey) + "/start";
  const payload = await requestJson(url, {
    method: "POST",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({
      user_id: input.userId,
      client_action_id: input.clientActionId,
      assignment_id: input.assignmentId,
      expected_assignment_version: input.expectedAssignmentVersion,
      expected_progress_version: input.expectedProgressVersion,
    }),
  });
  if (!isRecord(payload)) throw new Error("Lesson start API returned an invalid payload");
  const assignment = toLessonAssignment(payload.assignment);
  if (!assignment) throw new Error("Lesson start API returned an invalid assignment");
  return assignment;
}

export async function activateLessonMigration(input: {
  userId: string;
  trackId: string;
  knowledgeKey: string;
  assignmentId: string;
  expectedAssignmentVersion: number;
  clientActionId: string;
}): Promise<LessonAssignment> {
  const url = API_BASE_URL + "/api/learning-tracks/" + encodeURIComponent(input.trackId) + "/lessons/" + encodeURIComponent(input.knowledgeKey) + "/migrations/" + encodeURIComponent(input.assignmentId) + "/activate";
  const payload = await requestJson(url, {
    method: "POST",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({
      user_id: input.userId,
      client_action_id: input.clientActionId,
      expected_assignment_version: input.expectedAssignmentVersion,
    }),
  });
  if (!isRecord(payload)) throw new Error("Lesson migration API returned an invalid payload");
  const assignment = toLessonAssignment(payload.assignment);
  if (!assignment) throw new Error("Lesson migration API returned an invalid assignment");
  return assignment;
}

export async function fetchLessonGates(
  userId: string,
  trackId: string,
  knowledgeKey: string,
  signal?: AbortSignal,
): Promise<LessonGateList> {
  const query = new URLSearchParams({ user_id: userId });
  const url = `${API_BASE_URL}/api/learning-tracks/${encodeURIComponent(trackId)}/lessons/${encodeURIComponent(knowledgeKey)}/gates?${query.toString()}`;
  const payload = await requestJson(url, { signal });
  const gates = toLessonGateList(payload);
  if (!gates) throw new Error("Lesson Gate API returned an invalid payload");
  return gates;
}

export async function prepareLessonGate(input: {
  userId: string;
  trackId: string;
  knowledgeKey: string;
  gateKey: string;
  expectedTrackVersion: number;
  expectedProgressVersion: number;
  clientActionId: string;
}): Promise<LessonGatePrepareResponse> {
  const url = `${API_BASE_URL}/api/learning-tracks/${encodeURIComponent(input.trackId)}/lessons/${encodeURIComponent(input.knowledgeKey)}/gates/${encodeURIComponent(input.gateKey)}/prepare`;
  const payload = await requestJson(url, {
    method: "POST",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({
      user_id: input.userId,
      client_action_id: input.clientActionId,
      expected_track_version: input.expectedTrackVersion,
      expected_progress_version: input.expectedProgressVersion,
    }),
  });
  const response = toLessonGatePrepareResponse(payload);
  if (!response) throw new Error("Lesson Gate prepare API returned an invalid payload");
  return response;
}

export async function requestLessonGateHint(input: {
  userId: string;
  trackId: string;
  knowledgeKey: string;
  gateKey: string;
  expectedGateVersion: number;
  clientActionId: string;
}): Promise<LessonGateHint> {
  const url = `${API_BASE_URL}/api/learning-tracks/${encodeURIComponent(input.trackId)}/lessons/${encodeURIComponent(input.knowledgeKey)}/gates/${encodeURIComponent(input.gateKey)}/hints`;
  const payload = await requestJson(url, {
    method: "POST",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({
      user_id: input.userId,
      client_action_id: input.clientActionId,
      expected_gate_version: input.expectedGateVersion,
    }),
  });
  const hint = toLessonGateHint(payload);
  if (!hint) throw new Error("Lesson Gate hint API returned an invalid payload");
  return hint;
}

type LessonGateAttemptInput = {
  userId: string;
  trackId: string;
  knowledgeKey: string;
  gateKey: string;
  attemptType: "run" | "submit";
  expectedTrackVersion: number;
  expectedProgressVersion: number;
  expectedAssignmentVersion: number;
  expectedGateVersion: number;
  clientActionId: string;
} & (
  | { submission: string; reviewSubmission?: never }
  | { submission?: never; reviewSubmission: ModelCodeReviewSubmission }
);

export async function requestModelReviewEvidence(input: {
  userId: string;
  trackId: string;
  knowledgeKey: string;
  gateKey: string;
  expectedGateVersion: number;
  clientActionId: string;
}): Promise<ModelReviewEvidenceResponse> {
  const url = `${API_BASE_URL}/api/learning-tracks/${encodeURIComponent(input.trackId)}/lessons/${encodeURIComponent(input.knowledgeKey)}/gates/${encodeURIComponent(input.gateKey)}/evidence`;
  const payload = await requestJson(url, {
    method: "POST",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({
      user_id: input.userId,
      client_action_id: input.clientActionId,
      expected_gate_version: input.expectedGateVersion,
    }),
  });
  const evidence = toModelReviewEvidenceResponse(payload);
  if (!evidence) throw new Error("Model review evidence API returned an invalid payload");
  return evidence;
}

export async function createLessonGateAttempt(input: LessonGateAttemptInput): Promise<ExerciseAttemptState> {
  const url = `${API_BASE_URL}/api/learning-tracks/${encodeURIComponent(input.trackId)}/lessons/${encodeURIComponent(input.knowledgeKey)}/gates/${encodeURIComponent(input.gateKey)}/attempts`;
  const payload = await requestJson(url, {
    method: "POST",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({
      user_id: input.userId,
      client_action_id: input.clientActionId,
      attempt_type: input.attemptType,
      ...(input.reviewSubmission ? { review_submission: input.reviewSubmission } : { submission: input.submission }),
      expected_track_version: input.expectedTrackVersion,
      expected_progress_version: input.expectedProgressVersion,
      expected_assignment_version: input.expectedAssignmentVersion,
      expected_gate_version: input.expectedGateVersion,
    }),
  });
  const attempt = toExerciseAttemptState(payload);
  if (!attempt) throw new Error("Lesson Gate attempt API returned an invalid payload");
  return attempt;
}

export async function fetchExerciseAttempt(
  userId: string,
  trackId: string,
  knowledgeKey: string,
  attemptId: string,
  signal?: AbortSignal,
): Promise<ExerciseAttemptState> {
  const query = new URLSearchParams({ user_id: userId });
  const url = `${API_BASE_URL}/api/learning-tracks/${encodeURIComponent(trackId)}/lessons/${encodeURIComponent(knowledgeKey)}/attempts/${encodeURIComponent(attemptId)}?${query.toString()}`;
  const payload = await requestJson(url, { signal });
  const attempt = toExerciseAttemptState(payload);
  if (!attempt) throw new Error("Exercise Attempt API returned an invalid payload");
  return attempt;
}

export async function createModuleDiagnostic(input: {
  userId: string;
  trackId: string;
  moduleKey: string;
  expectedTrackVersion: number;
  clientActionId: string;
}): Promise<ModuleDiagnosticState> {
  const url = `${API_BASE_URL}/api/learning-tracks/${encodeURIComponent(input.trackId)}/modules/${encodeURIComponent(input.moduleKey)}/diagnostics`;
  const payload = await requestJson(url, {
    method: "POST",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({
      user_id: input.userId,
      client_action_id: input.clientActionId,
      expected_track_version: input.expectedTrackVersion,
    }),
  });
  const diagnostic = toModuleDiagnosticState(payload);
  if (!diagnostic) throw new Error("Module diagnostic API returned an invalid payload");
  return diagnostic;
}

export async function fetchModuleDiagnostic(
  userId: string,
  trackId: string,
  moduleKey: string,
  sessionId: string,
  signal?: AbortSignal,
): Promise<ModuleDiagnosticState> {
  const query = new URLSearchParams({ user_id: userId });
  const url = `${API_BASE_URL}/api/learning-tracks/${encodeURIComponent(trackId)}/modules/${encodeURIComponent(moduleKey)}/diagnostics/${encodeURIComponent(sessionId)}?${query.toString()}`;
  const payload = await requestJson(url, { signal });
  const diagnostic = toModuleDiagnosticState(payload);
  if (!diagnostic) throw new Error("Module diagnostic read API returned an invalid payload");
  return diagnostic;
}

export async function createModuleDiagnosticAttempt(input: {
  userId: string;
  trackId: string;
  moduleKey: string;
  sessionId: string;
  itemId: string;
  submission: string;
  expectedTrackVersion: number;
  expectedSessionVersion: number;
  clientActionId: string;
}): Promise<ExerciseAttemptState | ModuleDiagnosticState> {
  const url = `${API_BASE_URL}/api/learning-tracks/${encodeURIComponent(input.trackId)}/modules/${encodeURIComponent(input.moduleKey)}/diagnostics/${encodeURIComponent(input.sessionId)}/items/${encodeURIComponent(input.itemId)}/attempts`;
  const payload = await requestJson(url, {
    method: "POST",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({
      user_id: input.userId,
      client_action_id: input.clientActionId,
      submission: input.submission,
      expected_track_version: input.expectedTrackVersion,
      expected_session_version: input.expectedSessionVersion,
    }),
  });
  const diagnostic = toModuleDiagnosticState(payload);
  if (diagnostic) return diagnostic;
  const attempt = toExerciseAttemptState(payload);
  if (attempt) return attempt;
  throw new Error("Module diagnostic attempt API returned an invalid payload");
}

export async function confirmModuleDiagnosticSkip(input: {
  userId: string;
  trackId: string;
  moduleKey: string;
  sessionId: string;
  expectedTrackVersion: number;
  expectedSessionVersion: number;
  clientActionId: string;
}): Promise<ModuleDiagnosticState> {
  const url = `${API_BASE_URL}/api/learning-tracks/${encodeURIComponent(input.trackId)}/modules/${encodeURIComponent(input.moduleKey)}/diagnostics/${encodeURIComponent(input.sessionId)}/confirm-skip`;
  const payload = await requestJson(url, {
    method: "POST",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({
      user_id: input.userId,
      client_action_id: input.clientActionId,
      expected_track_version: input.expectedTrackVersion,
      expected_session_version: input.expectedSessionVersion,
    }),
  });
  const diagnostic = toModuleDiagnosticState(payload);
  if (!diagnostic) throw new Error("Module diagnostic confirmation returned an invalid payload");
  return diagnostic;
}

export async function fetchCurrentLearningPlanSession(
  userId: string,
  signal?: AbortSignal,
): Promise<LearningPlanSession | null> {
  const query = new URLSearchParams({ user_id: userId });
  const payload = await requestJson(`${API_BASE_URL}/api/learning-plan-sessions/current?${query.toString()}`, { signal });
  if (!isRecord(payload) || !("session" in payload)) throw new Error("Learning plan session API returned an invalid payload");
  if (payload.session === null) return null;
  const session = toLearningPlanSession(payload.session);
  if (!session) throw new Error("Learning plan session API returned an invalid session");
  return session;
}

export async function fetchLearningPlanSession(
  userId: string,
  sessionId: string,
  signal?: AbortSignal,
): Promise<LearningPlanSession> {
  const query = new URLSearchParams({ user_id: userId });
  const payload = await requestJson(
    `${API_BASE_URL}/api/learning-plan-sessions/${encodeURIComponent(sessionId)}?${query.toString()}`,
    { signal },
  );
  const session = isRecord(payload) ? toLearningPlanSession(payload.session) : null;
  if (!session) throw new Error("Learning plan session API returned an invalid session");
  return session;
}

export async function createLearningPlanSession(input: {
  userId: string;
  clientActionId: string;
  preferredLanguageId?: string;
}): Promise<LearningPlanSession> {
  const payload = await requestJson(`${API_BASE_URL}/api/learning-plan-sessions`, {
    method: "POST",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({
      user_id: input.userId,
      client_action_id: input.clientActionId,
      ...(input.preferredLanguageId ? { preferred_language_id: input.preferredLanguageId } : {}),
    }),
  });
  const session = isRecord(payload) ? toLearningPlanSession(payload.session) : null;
  if (!session) throw new Error("Learning plan session creation returned an invalid payload");
  return session;
}

export async function cancelLearningPlanSession(input: {
  userId: string;
  sessionId: string;
  expectedSessionVersion: number;
  clientActionId: string;
}): Promise<LearningPlanSession> {
  const payload = await requestJson(
    `${API_BASE_URL}/api/learning-plan-sessions/${encodeURIComponent(input.sessionId)}/cancel`,
    {
      method: "POST",
      headers: tutorMutationHeaders(input.clientActionId),
      body: JSON.stringify({
        user_id: input.userId,
        client_action_id: input.clientActionId,
        expected_session_version: input.expectedSessionVersion,
      }),
    },
  );
  const session = isRecord(payload) ? toLearningPlanSession(payload.session) : null;
  if (!session) throw new Error("Learning plan session cancellation returned an invalid payload");
  return session;
}

export async function confirmLearningPlanSession(input: {
  userId: string;
  session: LearningPlanSession;
  clientActionId: string;
}): Promise<{ session: LearningPlanSession; track: LearningTrackSummary }> {
  const draft = input.session.current_draft;
  if (!draft) throw new Error("Learning plan draft is not ready");
  const payload = await requestJson(
    `${API_BASE_URL}/api/learning-plan-sessions/${encodeURIComponent(input.session.session_id)}/confirm`,
    {
      method: "POST",
      headers: tutorMutationHeaders(input.clientActionId),
      body: JSON.stringify({
        user_id: input.userId,
        client_action_id: input.clientActionId,
        expected_session_version: input.session.version,
        draft_id: draft.draft_id,
        draft_version: draft.draft_version,
        content_hash: draft.content_hash,
      }),
    },
  );
  const session = isRecord(payload) ? toLearningPlanSession(payload.session) : null;
  const track = isRecord(payload) ? toLearningTrackSummary(payload.track) : null;
  if (!session || !track) throw new Error("Learning plan confirmation returned an invalid payload");
  return { session, track };
}

export function buildTutorConversationEventsUrl(conversationId: string, userId: string): string {
  const url = new URL(`/api/tutor/conversations/${encodeURIComponent(conversationId)}/events`, API_BASE_URL);
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

function parseTutorThreadTurnV2Capability(payload: unknown): TutorThreadTurnV2Capability | null {
  const keys = [
    "schema_version", "cutover_version", "desktop_contract_version", "env_allowed", "state",
    "generation", "summary_hash", "block_code", "effective_enabled", "counts",
    "prepared_at", "enabled_at", "updated_at",
  ];
  if (!isRecord(payload) || !hasExactKeys(payload, keys)) return null;
  if (payload.schema_version !== "tutor_thread_turn_v2_capability_v1" ||
      payload.cutover_version !== "tutor_thread_turn_v2_global_v1" ||
      payload.desktop_contract_version !== "tutor_thread_turn_v2_desktop_v1" ||
      typeof payload.env_allowed !== "boolean" || typeof payload.effective_enabled !== "boolean" ||
      !isNonNegativeSafeInteger(payload.generation) || !isNullableString(payload.summary_hash) ||
      !isNullableString(payload.block_code) || !isNullableString(payload.prepared_at) ||
      !isNullableString(payload.enabled_at) || !isNullableString(payload.updated_at) ||
      !isRecord(payload.counts) || !isTutorThreadTurnV2State(payload.state)) return null;
  for (const value of Object.values(payload.counts)) {
    if (typeof value === "boolean" || typeof value === "string" || isNonNegativeSafeInteger(value)) continue;
    if (!isRecord(value) || Object.values(value).some((item) => !isNonNegativeSafeInteger(item))) return null;
  }
  return {
    schema_version: "tutor_thread_turn_v2_capability_v1", cutover_version: "tutor_thread_turn_v2_global_v1",
    desktop_contract_version: "tutor_thread_turn_v2_desktop_v1", env_allowed: payload.env_allowed,
    state: payload.state, generation: payload.generation, summary_hash: payload.summary_hash,
    block_code: payload.block_code, effective_enabled: payload.effective_enabled,
    counts: payload.counts as TutorThreadTurnV2Capability["counts"], prepared_at: payload.prepared_at,
    enabled_at: payload.enabled_at, updated_at: payload.updated_at,
  };
}

function isTutorThreadTurnV2State(value: unknown): value is TutorThreadTurnV2Capability["state"] {
  return value === "idle" || value === "preparing" || value === "blocked" || value === "ready" || value === "enabled";
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

const LEARNING_TRACK_SUMMARY_KEYS = [
  "track_id", "language_id", "language_display_name", "goal_text", "target_level", "status", "version",
  "active_revision_id", "active_plan_title", "current_knowledge_key", "current_knowledge_title", "progress",
  "review_due_count", "execution_tier", "execution_disclosure", "last_learned_at", "updated_at",
] as const;

function toLearningTrackDetail(payload: unknown): LearningTrackDetail | null {
  if (!isRecord(payload) || !hasExactKeys(payload, [...LEARNING_TRACK_SUMMARY_KEYS, "created_at", "archived_at"])) return null;
  const summary = toLearningTrackSummaryRecord(payload, false);
  if (!summary || !isNullableString(payload.created_at) || !isNullableString(payload.archived_at)) return null;
  return { ...summary, created_at: payload.created_at, archived_at: payload.archived_at };
}

function toLearningRoadmap(payload: unknown): LearningRoadmap | null {
  if (
    !isRecord(payload) || !hasExactKeys(payload, ["track_id", "active_revision_id", "title", "target_level", "modules"]) ||
    !isString(payload.track_id) || !isString(payload.active_revision_id) || !isString(payload.title) ||
    !isString(payload.target_level) || !Array.isArray(payload.modules)
  ) return null;
  const modules = payload.modules.map(toLearningRoadmapModule);
  if (modules.some((item) => item === null)) return null;
  return {
    track_id: payload.track_id,
    active_revision_id: payload.active_revision_id,
    title: payload.title,
    target_level: payload.target_level,
    modules: modules.filter((item): item is LearningRoadmapModule => item !== null),
  };
}

function toLearningRoadmapModule(payload: unknown): LearningRoadmapModule | null {
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, ["module_id", "module_key", "title", "description", "order_index", "is_core", "is_skippable", "nodes"]) ||
    !isString(payload.module_id) || !isString(payload.module_key) || !isString(payload.title) ||
    !isString(payload.description) || !isNonNegativeSafeInteger(payload.order_index) ||
    typeof payload.is_core !== "boolean" || typeof payload.is_skippable !== "boolean" || !Array.isArray(payload.nodes)
  ) return null;
  const nodes = payload.nodes.map(toLearningRoadmapNode);
  if (nodes.some((item) => item === null)) return null;
  return {
    module_id: payload.module_id, module_key: payload.module_key, title: payload.title,
    description: payload.description, order_index: payload.order_index, is_core: payload.is_core,
    is_skippable: payload.is_skippable,
    nodes: nodes.filter((item): item is LearningRoadmapNode => item !== null),
  };
}

function toLearningRoadmapNode(payload: unknown): LearningRoadmapNode | null {
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, [
      "node_id", "knowledge_key", "title", "description", "order_index", "is_core", "prerequisite_keys",
      "required_capabilities", "progress_status", "progress_version", "mastery_level", "mastery_confidence",
    ]) ||
    !isString(payload.node_id) || !isString(payload.knowledge_key) || !isString(payload.title) ||
    !isString(payload.description) || !isNonNegativeSafeInteger(payload.order_index) || typeof payload.is_core !== "boolean" ||
    !isStringArray(payload.prerequisite_keys) || !isStringArray(payload.required_capabilities) ||
    !isLearningProgressStatus(payload.progress_status) || !isNonNegativeSafeInteger(payload.progress_version) ||
    !isString(payload.mastery_level) || !isScore(payload.mastery_confidence)
  ) return null;
  return {
    node_id: payload.node_id, knowledge_key: payload.knowledge_key, title: payload.title,
    description: payload.description, order_index: payload.order_index, is_core: payload.is_core,
    prerequisite_keys: payload.prerequisite_keys, required_capabilities: payload.required_capabilities,
    progress_status: payload.progress_status, progress_version: payload.progress_version,
    mastery_level: payload.mastery_level, mastery_confidence: payload.mastery_confidence,
  };
}

function toReviewQueue(payload: unknown): ReviewQueue | null {
  if (
    !isRecord(payload) || !hasExactKeys(payload, ["track_id", "as_of", "due_count", "items", "critical_prerequisite_gate"]) ||
    !isString(payload.track_id) || !isNullableString(payload.as_of) || !isNonNegativeSafeInteger(payload.due_count) ||
    !Array.isArray(payload.items)
  ) return null;
  const items = payload.items.map(toReviewQueueItem);
  if (items.some((item) => item === null)) return null;
  const critical = payload.critical_prerequisite_gate === null ? null : toReviewQueueItem(payload.critical_prerequisite_gate);
  if (payload.critical_prerequisite_gate !== null && !critical) return null;
  return {
    track_id: payload.track_id, as_of: payload.as_of, due_count: payload.due_count,
    items: items.filter((item): item is ReviewQueueItem => item !== null),
    critical_prerequisite_gate: critical,
  };
}

function toReviewQueueItem(payload: unknown): ReviewQueueItem | null {
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, ["schedule_id", "knowledge_key", "title", "due_at", "risk_level", "critical_prerequisite_gate", "mastery", "required_capabilities", "schedule_version"]) ||
    !isString(payload.schedule_id) || !isString(payload.knowledge_key) || !isString(payload.title) ||
    !isNullableString(payload.due_at) || !isReviewRiskLevel(payload.risk_level) ||
    typeof payload.critical_prerequisite_gate !== "boolean" || !isRecord(payload.mastery) ||
    !isStringArray(payload.required_capabilities) || !isPositiveSafeInteger(payload.schedule_version)
  ) return null;
  return {
    schedule_id: payload.schedule_id, knowledge_key: payload.knowledge_key, title: payload.title,
    due_at: payload.due_at, risk_level: payload.risk_level,
    critical_prerequisite_gate: payload.critical_prerequisite_gate, mastery: payload.mastery,
    required_capabilities: payload.required_capabilities, schedule_version: payload.schedule_version,
  };
}

function toReviewSession(payload: unknown): ReviewSession | null {
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, [
      "session_id", "track_id", "knowledge_key", "plan_revision_id", "state", "stage", "failure_code",
      "recoverable", "version", "context_snapshot", "context_snapshot_hash", "items", "finalization",
      "started_at", "terminal_at", "idempotent_replayed",
    ]) ||
    !isString(payload.session_id) || !isString(payload.track_id) || !isString(payload.knowledge_key) ||
    !isString(payload.plan_revision_id) || !isReviewSessionState(payload.state) || !isReviewSessionStage(payload.stage) ||
    !isNullableString(payload.failure_code) || typeof payload.recoverable !== "boolean" ||
    !isPositiveSafeInteger(payload.version) || !isRecord(payload.context_snapshot) ||
    !isSha256(payload.context_snapshot_hash) || !Array.isArray(payload.items) ||
    !isNullableString(payload.started_at) || !isNullableString(payload.terminal_at) ||
    typeof payload.idempotent_replayed !== "boolean"
  ) return null;
  const items = payload.items.map(toReviewSessionItem);
  if (items.some((item) => item === null)) return null;
  const finalization = payload.finalization === null ? null : toReviewFinalization(payload.finalization);
  if (payload.finalization !== null && !finalization) return null;
  return {
    session_id: payload.session_id, track_id: payload.track_id, knowledge_key: payload.knowledge_key,
    plan_revision_id: payload.plan_revision_id, state: payload.state, stage: payload.stage,
    failure_code: payload.failure_code, recoverable: payload.recoverable, version: payload.version,
    context_snapshot: payload.context_snapshot, context_snapshot_hash: payload.context_snapshot_hash,
    items: items.filter((item): item is ReviewSessionItem => item !== null), finalization,
    started_at: payload.started_at, terminal_at: payload.terminal_at,
    idempotent_replayed: payload.idempotent_replayed,
  };
}

function toReviewSessionItem(payload: unknown): ReviewSessionItem | null {
  if (
    !isRecord(payload) || !hasExactKeys(payload, ["item_id", "order_index", "version", "exercise", "attempt"]) ||
    !isString(payload.item_id) || !isNonNegativeSafeInteger(payload.order_index) || !isPositiveSafeInteger(payload.version)
  ) return null;
  const exercise = toReviewExercise(payload.exercise);
  const attempt = payload.attempt === null ? null : toReviewSessionAttemptSummary(payload.attempt);
  if (!exercise || (payload.attempt !== null && !attempt)) return null;
  return { item_id: payload.item_id, order_index: payload.order_index, version: payload.version, exercise, attempt };
}

function toReviewExercise(payload: unknown): ReviewSessionItem["exercise"] | null {
  if (
    !isRecord(payload) || !hasExactKeys(payload, [
      "exercise_version_id", "exercise_type", "title", "learner_prompt", "starter_artifact",
      "required_capabilities", "content_hash", "execution_tier", "execution_disclosure",
    ]) ||
    !isString(payload.exercise_version_id) || !isExerciseType(payload.exercise_type) || !isString(payload.title) ||
    !isStringArray(payload.required_capabilities) || !isSha256(payload.content_hash) ||
    !isExecutionTier(payload.execution_tier) || !isString(payload.execution_disclosure)
  ) return null;
  if (payload.exercise_type === "model_code_review") {
    const prompt = toModelReviewPrompt(payload.learner_prompt);
    const artifact = toModelReviewArtifact(payload.starter_artifact);
    if (!prompt || !artifact) return null;
    return {
      exercise_version_id: payload.exercise_version_id, exercise_type: payload.exercise_type, title: payload.title,
      learner_prompt: prompt, starter_artifact: artifact, required_capabilities: payload.required_capabilities,
      content_hash: payload.content_hash, execution_tier: payload.execution_tier,
      execution_disclosure: payload.execution_disclosure,
    };
  }
  if (!isRecord(payload.learner_prompt) || !isRecord(payload.starter_artifact)) return null;
  return {
    exercise_version_id: payload.exercise_version_id, exercise_type: payload.exercise_type, title: payload.title,
    learner_prompt: payload.learner_prompt, starter_artifact: payload.starter_artifact,
    required_capabilities: payload.required_capabilities, content_hash: payload.content_hash,
    execution_tier: payload.execution_tier, execution_disclosure: payload.execution_disclosure,
  };
}

function toReviewSessionAttemptSummary(payload: unknown): ReviewSessionAttemptSummary | null {
  if (
    !isRecord(payload) || !hasExactKeys(payload, [
      "attempt_id", "status", "independence", "assistance_kind", "execution_job_id", "execution_job_state", "result",
    ]) || !isString(payload.attempt_id) || (payload.status !== "pending" && payload.status !== "terminal") ||
    !isExerciseIndependence(payload.independence) || !isModelReviewAssistanceKind(payload.assistance_kind) ||
    !isNullableString(payload.execution_job_id) || !isNullableString(payload.execution_job_state)
  ) return null;
  const result = payload.result === null ? null : toLessonGateResult(payload.result);
  if ((payload.result !== null && !result) || (payload.status === "terminal") !== (result !== null)) return null;
  return {
    attempt_id: payload.attempt_id, status: payload.status, independence: payload.independence,
    assistance_kind: payload.assistance_kind, execution_job_id: payload.execution_job_id,
    execution_job_state: payload.execution_job_state, result,
  };
}

function toReviewFinalization(payload: unknown): ReviewSession["finalization"] | null {
  if (
    !isRecord(payload) || !hasExactKeys(payload, ["rating", "aggregate", "result_hash"]) ||
    !isReviewRating(payload.rating) || !isRecord(payload.aggregate) || !isSha256(payload.result_hash)
  ) return null;
  return { rating: payload.rating, aggregate: payload.aggregate, result_hash: payload.result_hash };
}

function toReviewHint(payload: unknown): ReviewHint | null {
  if (
    !isRecord(payload) || !hasExactKeys(payload, ["hint_id", "hint_level", "safe_hint", "created_at"]) ||
    !isString(payload.hint_id) || !isPositiveSafeInteger(payload.hint_level) || payload.hint_level > 3 ||
    !isRecord(payload.safe_hint) || !isNullableString(payload.created_at)
  ) return null;
  return { hint_id: payload.hint_id, hint_level: payload.hint_level, safe_hint: payload.safe_hint, created_at: payload.created_at };
}

function toReviewAttempt(payload: unknown): ReviewAttempt | null {
  if (!isRecord(payload)) return null;
  const baseKeys = [
    "attempt_id", "attempt_type", "track_id", "session_id", "item_id", "knowledge_key", "session_version",
    "exercise_version_id", "submission_hash", "independence", "assistance_kind", "accepted_at", "status",
    "execution_job_id", "execution_job_state", "result", "idempotent_replayed",
  ];
  const withTierKeys = [...baseKeys, "execution_tier", "execution_disclosure"];
  if (!hasExactKeys(payload, baseKeys) && !hasExactKeys(payload, withTierKeys)) return null;
  if (
    !isString(payload.attempt_id) || payload.attempt_type !== "review_submit" || !isString(payload.track_id) ||
    !isString(payload.session_id) || !isString(payload.item_id) || !isString(payload.knowledge_key) ||
    !isPositiveSafeInteger(payload.session_version) || !isString(payload.exercise_version_id) ||
    !isSha256(payload.submission_hash) || !isExerciseIndependence(payload.independence) ||
    !isModelReviewAssistanceKind(payload.assistance_kind) || !isNullableString(payload.accepted_at) ||
    (payload.status !== "pending" && payload.status !== "terminal") || !isNullableString(payload.execution_job_id) ||
    !isNullableString(payload.execution_job_state) || typeof payload.idempotent_replayed !== "boolean"
  ) return null;
  const result = payload.result === null ? null : toLessonGateResult(payload.result);
  if ((payload.result !== null && !result) || (payload.status === "terminal") !== (result !== null)) return null;
  if (payload.execution_tier !== undefined && (!isExecutionTier(payload.execution_tier) || !isString(payload.execution_disclosure))) return null;
  return {
    attempt_id: payload.attempt_id, attempt_type: "review_submit", track_id: payload.track_id,
    session_id: payload.session_id, item_id: payload.item_id, knowledge_key: payload.knowledge_key,
    session_version: payload.session_version, exercise_version_id: payload.exercise_version_id,
    submission_hash: payload.submission_hash, independence: payload.independence,
    assistance_kind: payload.assistance_kind, accepted_at: payload.accepted_at, status: payload.status,
    execution_job_id: payload.execution_job_id, execution_job_state: payload.execution_job_state, result,
    idempotent_replayed: payload.idempotent_replayed,
    ...(payload.execution_tier !== undefined ? {
      execution_tier: payload.execution_tier,
      execution_disclosure: payload.execution_disclosure as string,
    } : {}),
  };
}

function toLearningTrackSummary(payload: unknown): LearningTrackSummary | null {
  return toLearningTrackSummaryRecord(payload, true);
}

function toLearningTrackSummaryRecord(payload: unknown, requireExact: boolean): LearningTrackSummary | null {
  if (
    !isRecord(payload) || (requireExact && !hasExactKeys(payload, [...LEARNING_TRACK_SUMMARY_KEYS])) ||
    !isString(payload.track_id) || !isString(payload.language_id) || !isString(payload.language_display_name) ||
    !isString(payload.goal_text) || !isString(payload.target_level) || !isLearningTrackStatus(payload.status) ||
    !isPositiveSafeInteger(payload.version) || !isString(payload.active_revision_id) ||
    !isString(payload.active_plan_title) || !isNullableString(payload.current_knowledge_key) ||
    !isNullableString(payload.current_knowledge_title) || !isRecord(payload.progress) ||
    !hasExactKeys(payload.progress, ["total", "completed", "in_progress", "review_due", "percent"]) ||
    !isNonNegativeSafeInteger(payload.progress.total) || !isNonNegativeSafeInteger(payload.progress.completed) ||
    !isNonNegativeSafeInteger(payload.progress.in_progress) || !isNonNegativeSafeInteger(payload.progress.review_due) ||
    typeof payload.progress.percent !== "number" || !Number.isFinite(payload.progress.percent) ||
    payload.progress.percent < 0 || payload.progress.percent > 100 || !isNonNegativeSafeInteger(payload.review_due_count) ||
    !isExecutionTier(payload.execution_tier) || !isString(payload.execution_disclosure) ||
    !isNullableString(payload.last_learned_at) || !isNullableString(payload.updated_at)
  ) return null;
  return {
    track_id: payload.track_id, language_id: payload.language_id, language_display_name: payload.language_display_name,
    goal_text: payload.goal_text, target_level: payload.target_level, status: payload.status, version: payload.version,
    active_revision_id: payload.active_revision_id, active_plan_title: payload.active_plan_title,
    current_knowledge_key: payload.current_knowledge_key, current_knowledge_title: payload.current_knowledge_title,
    progress: {
      total: payload.progress.total, completed: payload.progress.completed,
      in_progress: payload.progress.in_progress, review_due: payload.progress.review_due,
      percent: payload.progress.percent,
    },
    review_due_count: payload.review_due_count, execution_tier: payload.execution_tier,
    execution_disclosure: payload.execution_disclosure, last_learned_at: payload.last_learned_at,
    updated_at: payload.updated_at,
  };
}

function toLessonDocumentState(payload: unknown): LessonDocumentState | null {
  if (
    !isRecord(payload) || !isLessonPublicStatus(payload.status) ||
    !isString(payload.track_id) || !isString(payload.module_key) ||
    typeof payload.module_diagnostic_allowed !== "boolean" || !isString(payload.knowledge_key) ||
    !isNonNegativeSafeInteger(payload.track_version) ||
    !isNonNegativeSafeInteger(payload.progress_version) || !isString(payload.progress_status)
  ) return null;
  const common = {
    status: payload.status,
    track_id: payload.track_id,
    module_key: payload.module_key,
    module_diagnostic_allowed: payload.module_diagnostic_allowed,
    knowledge_key: payload.knowledge_key,
    track_version: payload.track_version,
    progress_version: payload.progress_version,
    progress_status: payload.progress_status,
  };
  if (payload.status === "ready") {
    if (!hasExactKeys(payload, ["status", "track_id", "module_key", "module_diagnostic_allowed", "knowledge_key", "track_version", "progress_version", "progress_status", "assignment", "document", "sources", "update"])) return null;
    const assignment = toLessonAssignment(payload.assignment);
    const document = toLessonDocument(payload.document);
    if (!assignment || !document || !Array.isArray(payload.sources)) return null;
    const sources = payload.sources.map(toLessonCitation);
    if (sources.some((item) => item === null)) return null;
    const update = payload.update === null ? null : toLessonUpdateProposal(payload.update);
    if (payload.update !== null && !update) return null;
    const citationIds = new Set(sources.flatMap((source) => source ? [source.citation_id] : []));
    if (document.blocks.some((block) => block.citation_ids.some((id) => !citationIds.has(id)))) return null;
    return {
      ...common,
      assignment,
      document,
      sources: sources.filter((item): item is LessonCitation => item !== null),
      update,
      authoring_run: null,
    };
  }
  if (payload.status === "missing") {
    if (!hasExactKeys(payload, ["status", "track_id", "module_key", "module_diagnostic_allowed", "knowledge_key", "track_version", "progress_version", "progress_status"])) return null;
    return { ...common, assignment: null, document: null, sources: [], update: null, authoring_run: null };
  }
  if (!hasExactKeys(payload, ["status", "track_id", "module_key", "module_diagnostic_allowed", "knowledge_key", "track_version", "progress_version", "progress_status", "authoring_run"])) return null;
  const run = toLessonAuthoringRun(payload.authoring_run);
  if (!run) return null;
  return { ...common, assignment: null, document: null, sources: [], update: null, authoring_run: run };
}

function toLessonPrepareResponse(payload: unknown): LessonPrepareResponse | null {
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, ["status", "track_id", "knowledge_key", "authoring_run", "idempotent_replayed"]) ||
    !isLessonPublicStatus(payload.status) || !isString(payload.track_id) ||
    !isString(payload.knowledge_key) || typeof payload.idempotent_replayed !== "boolean"
  ) return null;
  const run = payload.authoring_run === null ? null : toLessonAuthoringRun(payload.authoring_run);
  if (payload.authoring_run !== null && !run) return null;
  return {
    status: payload.status,
    track_id: payload.track_id,
    knowledge_key: payload.knowledge_key,
    authoring_run: run,
    idempotent_replayed: payload.idempotent_replayed,
  };
}

function toLessonGateList(payload: unknown): LessonGateList | null {
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, ["track_id", "knowledge_key", "track_version", "progress_version", "assignment_id", "assignment_version", "items"]) ||
    !isString(payload.track_id) || !isString(payload.knowledge_key) ||
    !isNonNegativeSafeInteger(payload.track_version) || !isNonNegativeSafeInteger(payload.progress_version) ||
    !isString(payload.assignment_id) || !isNonNegativeSafeInteger(payload.assignment_version) ||
    !Array.isArray(payload.items)
  ) return null;
  const items = payload.items.map(toLessonGateItem);
  if (items.some((item) => item === null)) return null;
  return {
    track_id: payload.track_id,
    knowledge_key: payload.knowledge_key,
    track_version: payload.track_version,
    progress_version: payload.progress_version,
    assignment_id: payload.assignment_id,
    assignment_version: payload.assignment_version,
    items: items.filter((item): item is LessonGateItem => item !== null),
  };
}

function toLessonGatePrepareResponse(payload: unknown): LessonGatePrepareResponse | null {
  if (!isRecord(payload) || typeof payload.idempotent_replayed !== "boolean") return null;
  if (payload.status === "ready") {
    if (!hasExactKeys(payload, ["status", "gate", "idempotent_replayed"])) return null;
    const gate = toLessonGateItem(payload.gate);
    return gate ? { status: "ready", gate, idempotent_replayed: payload.idempotent_replayed } : null;
  }
  if (payload.status !== "preparing" && payload.status !== "failed") return null;
  if (!hasExactKeys(payload, ["status", "gate", "review_authoring_run", "idempotent_replayed"])) return null;
  const gate = payload.gate === null ? null : toLessonGateItem(payload.gate);
  const run = toModelReviewAuthoringRun(payload.review_authoring_run);
  if ((payload.gate !== null && !gate) || !run) return null;
  return { status: payload.status, gate, review_authoring_run: run, idempotent_replayed: payload.idempotent_replayed };
}

function toModelReviewAuthoringRun(payload: unknown): ModelReviewAuthoringRun | null {
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, ["run_id", "state", "attempt_count", "failure_code", "failure_message"]) ||
    !isString(payload.run_id) || !isModelReviewAuthoringState(payload.state) ||
    !isNonNegativeSafeInteger(payload.attempt_count) || !isNullableString(payload.failure_code) ||
    !isNullableString(payload.failure_message)
  ) return null;
  return {
    run_id: payload.run_id,
    state: payload.state,
    attempt_count: payload.attempt_count,
    failure_code: payload.failure_code,
    failure_message: payload.failure_message,
  };
}

function toModelReviewEvidenceResponse(payload: unknown): ModelReviewEvidenceResponse | null {
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, ["evidence_id", "evidence", "assistance_kind", "gate_version", "created_at", "idempotent_replayed"]) ||
    !isString(payload.evidence_id) || payload.assistance_kind !== "validation_evidence_viewed" ||
    !isNonNegativeSafeInteger(payload.gate_version) || !isNullableString(payload.created_at) ||
    typeof payload.idempotent_replayed !== "boolean"
  ) return null;
  const evidence = toModelReviewVisibleEvidence(payload.evidence);
  return evidence ? {
    evidence_id: payload.evidence_id, evidence, assistance_kind: "validation_evidence_viewed",
    gate_version: payload.gate_version, created_at: payload.created_at,
    idempotent_replayed: payload.idempotent_replayed,
  } : null;
}

function toModelReviewVisibleEvidence(payload: unknown): ModelReviewVisibleEvidence | null {
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, ["schema_version", "execution_claim", "checks"]) ||
    payload.schema_version !== "model_code_review_visible_evidence_v1" ||
    payload.execution_claim !== "prepublication_only" || !Array.isArray(payload.checks)
  ) return null;
  const checks = payload.checks.map((item) => {
    if (
      !isRecord(item) || !hasExactKeys(item, ["check_type", "status", "safe_code"]) ||
      !isVisibleEvidenceCheckType(item.check_type) ||
      (item.status !== "passed" && item.status !== "not_applicable") || !isString(item.safe_code)
    ) return null;
    return { check_type: item.check_type, status: item.status, safe_code: item.safe_code };
  });
  if (checks.some((item) => item === null)) return null;
  const parsed = checks.filter((item): item is ModelReviewVisibleEvidence["checks"][number] => item !== null);
  if (new Set(parsed.map((item) => item.check_type)).size !== parsed.length) return null;
  return { schema_version: "model_code_review_visible_evidence_v1", execution_claim: "prepublication_only", checks: parsed };
}

function toLessonGateHint(payload: unknown): LessonGateHint | null {
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, ["hint_id", "hint_level", "hint_policy_version", "safe_hint", "gate_version", "created_at", "idempotent_replayed"]) ||
    !isString(payload.hint_id) || !isNonNegativeSafeInteger(payload.hint_level) ||
    !isString(payload.hint_policy_version) || !isRecord(payload.safe_hint) ||
    !isNonNegativeSafeInteger(payload.gate_version) || !isNullableString(payload.created_at) ||
    typeof payload.idempotent_replayed !== "boolean"
  ) return null;
  return {
    hint_id: payload.hint_id,
    hint_level: payload.hint_level,
    hint_policy_version: payload.hint_policy_version,
    safe_hint: payload.safe_hint,
    gate_version: payload.gate_version,
    created_at: payload.created_at,
    idempotent_replayed: payload.idempotent_replayed,
  };
}

function toLessonGateItem(payload: unknown): LessonGateItem | null {
  if (
    !isRecord(payload) || !isString(payload.gate_key) || !isLessonGateKind(payload.gate_kind) ||
    !isString(payload.assessment_contract_version) || !isStringArray(payload.required_capabilities) ||
    !isString(payload.learner_prompt) || !Array.isArray(payload.allowed_actions) ||
    !payload.allowed_actions.every(isLessonGateAction)
  ) return null;
  const common = {
    gate_key: payload.gate_key,
    gate_kind: payload.gate_kind,
    assessment_contract_version: payload.assessment_contract_version,
    required_capabilities: payload.required_capabilities,
    learner_prompt: payload.learner_prompt,
    allowed_actions: payload.allowed_actions,
  };
  if (payload.status === "unbound" || payload.status === "preparing" || payload.status === "failed") {
    if (
      !hasExactKeys(payload, [
        "gate_key", "gate_kind", "assessment_contract_version", "required_capabilities", "learner_prompt",
        "status", "allowed_actions", "exercise", "review_authoring_run",
      ]) ||
      payload.exercise !== null
    ) return null;
    const run = payload.review_authoring_run === null ? null : toModelReviewAuthoringRun(payload.review_authoring_run);
    if (payload.review_authoring_run !== null && !run) return null;
    if (payload.status !== "unbound" && !run) return null;
    return { ...common, status: payload.status, exercise: null, review_authoring_run: run };
  }
  if (
    !hasExactKeys(payload, [
      "gate_key", "gate_kind", "assessment_contract_version", "required_capabilities", "learner_prompt",
      "binding_id", "binding_contract_hash", "requirement_kind", "pass_policy_version", "pass_threshold",
      "execution_requirement", "status", "gate_version", "attempt_count", "best_score", "latest_attempt_id",
      "passed_at", "execution_tier", "execution_disclosure", "allowed_actions", "exercise", "latest_result",
    ]) ||
    !isString(payload.binding_id) || !isString(payload.binding_contract_hash) ||
    !isGateRequirementKind(payload.requirement_kind) || !isString(payload.pass_policy_version) ||
    !isScore(payload.pass_threshold) || !isExecutionRequirement(payload.execution_requirement) ||
    !isLessonGateState(payload.status) || !isNonNegativeSafeInteger(payload.gate_version) ||
    !isNonNegativeSafeInteger(payload.attempt_count) || !isScore(payload.best_score) ||
    !isNullableString(payload.latest_attempt_id) || !isNullableString(payload.passed_at) ||
    !isExecutionTier(payload.execution_tier) || !isString(payload.execution_disclosure)
  ) return null;
  const exercise = toLessonGateExercise(payload.exercise, true);
  const latestResult = payload.latest_result === null ? null : toLessonGateResult(payload.latest_result);
  if (!exercise || (payload.latest_result !== null && !latestResult)) return null;
  return {
    ...common,
    binding_id: payload.binding_id,
    binding_contract_hash: payload.binding_contract_hash,
    requirement_kind: payload.requirement_kind,
    pass_policy_version: payload.pass_policy_version,
    pass_threshold: payload.pass_threshold,
    execution_requirement: payload.execution_requirement,
    status: payload.status,
    gate_version: payload.gate_version,
    attempt_count: payload.attempt_count,
    best_score: payload.best_score,
    latest_attempt_id: payload.latest_attempt_id,
    passed_at: payload.passed_at,
    execution_tier: payload.execution_tier,
    execution_disclosure: payload.execution_disclosure,
    exercise,
    latest_result: latestResult,
  };
}

function toLessonGateExercise(payload: unknown, requireGateFields: boolean): LessonGateExercise | null {
  if (
    !isRecord(payload) || !isString(payload.exercise_version_id) || !isString(payload.exercise_key) ||
    !isExerciseType(payload.exercise_type) || !isString(payload.version) || !isString(payload.title)
  ) return null;
  const expectedKeys = requireGateFields
    ? ["exercise_version_id", "exercise_key", "exercise_type", "version", "title", "learner_prompt", "starter_artifact", "required_capabilities", "content_hash"]
    : ["exercise_version_id", "exercise_key", "exercise_type", "version", "title", "learner_prompt", "starter_artifact"];
  if (!hasExactKeys(payload, expectedKeys)) return null;
  if (requireGateFields && (!isStringArray(payload.required_capabilities) || !isString(payload.content_hash))) return null;
  const shared = {
    exercise_version_id: payload.exercise_version_id,
    exercise_key: payload.exercise_key,
    version: payload.version,
    title: payload.title,
  };
  const gateFields = requireGateFields
    ? { required_capabilities: isStringArray(payload.required_capabilities) ? payload.required_capabilities : [], content_hash: typeof payload.content_hash === "string" ? payload.content_hash : "" }
    : {};
  if (payload.exercise_type === "model_code_review") {
    const prompt = toModelReviewPrompt(payload.learner_prompt);
    const artifact = toModelReviewArtifact(payload.starter_artifact);
    return prompt && artifact ? { ...shared, ...gateFields, exercise_type: "model_code_review", learner_prompt: prompt, starter_artifact: artifact } : null;
  }
  if (!isRecord(payload.learner_prompt) || !isRecord(payload.starter_artifact)) return null;
  return { ...shared, ...gateFields, exercise_type: payload.exercise_type, learner_prompt: payload.learner_prompt, starter_artifact: payload.starter_artifact };
}

function toLessonGateResult(payload: unknown): LessonGateResult | null {
  if (!isRecord(payload) || !isExerciseAttemptOutcome(payload.outcome) || !isScore(payload.score) || !isRecord(payload.safe_feedback) || !isNullableString(payload.terminal_at)) return null;
  const baseKeys = ["outcome", "score", "safe_feedback", "terminal_at"];
  const fullKeys = [...baseKeys, "capability_scores"];
  if (!hasExactKeys(payload, baseKeys) && !hasExactKeys(payload, fullKeys)) return null;
  const capabilityScores = payload.capability_scores === undefined ? undefined : toScoreRecord(payload.capability_scores);
  if (payload.capability_scores !== undefined && !capabilityScores) return null;
  const safeFeedback = payload.safe_feedback.status === "model_code_review_evaluated"
    ? toModelReviewSafeFeedback(payload.safe_feedback)
    : payload.safe_feedback;
  if (!safeFeedback) return null;
  return {
    outcome: payload.outcome,
    score: payload.score,
    safe_feedback: safeFeedback,
    ...(capabilityScores ? { capability_scores: capabilityScores } : {}),
    terminal_at: payload.terminal_at,
  };
}

function toModelReviewPrompt(payload: unknown): ModelReviewPrompt | null {
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, ["schema_version", "requirements", "review_scope", "evidence_boundary", "learner_instruction"]) ||
    payload.schema_version !== "model_code_review_prompt_v1" || !isStringArray(payload.requirements) ||
    !isStringArray(payload.review_scope) || payload.evidence_boundary !== "prepublication_verified" ||
    !isString(payload.learner_instruction) || payload.requirements.length === 0 || payload.review_scope.length === 0
  ) return null;
  return {
    schema_version: "model_code_review_prompt_v1", requirements: payload.requirements,
    review_scope: payload.review_scope, evidence_boundary: "prepublication_verified",
    learner_instruction: payload.learner_instruction,
  };
}

function toModelReviewArtifact(payload: unknown): ModelReviewArtifact | null {
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, ["schema_version", "language_id", "runtime_label", "model_code", "code_hash", "line_count"]) ||
    payload.schema_version !== "model_code_review_artifact_v1" || !isString(payload.language_id) ||
    !isString(payload.runtime_label) || !isString(payload.model_code) ||
    !isSha256(payload.code_hash) || !isPositiveSafeInteger(payload.line_count) ||
    normalizedLineCount(payload.model_code) !== payload.line_count
  ) return null;
  return {
    schema_version: "model_code_review_artifact_v1", language_id: payload.language_id,
    runtime_label: payload.runtime_label, model_code: payload.model_code, code_hash: payload.code_hash,
    line_count: payload.line_count,
  };
}

function toModelReviewSafeFeedback(payload: unknown): ModelReviewSafeFeedback | null {
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, ["status", "message", "execution_claim", "assistance_kind", "score_breakdown", "finding_feedback", "omission_band", "next_action"]) ||
    payload.status !== "model_code_review_evaluated" || !isString(payload.message) ||
    payload.execution_claim !== "not_run" || !isModelReviewAssistanceKind(payload.assistance_kind) ||
    !Array.isArray(payload.finding_feedback) ||
    (payload.omission_band !== "none" && payload.omission_band !== "limited" && payload.omission_band !== "major") ||
    (payload.next_action !== "advance_next" && payload.next_action !== "review_variant" && payload.next_action !== "show_hint")
  ) return null;
  const scoreBreakdown = toModelReviewScoreBreakdown(payload.score_breakdown);
  const findingFeedback = payload.finding_feedback.map(toModelReviewFindingFeedback);
  if (!scoreBreakdown || findingFeedback.some((item) => item === null)) return null;
  const parsed = findingFeedback.filter((item): item is ModelReviewFindingFeedback => item !== null);
  if (new Set(parsed.map((item) => item.client_finding_id)).size !== parsed.length) return null;
  return {
    status: "model_code_review_evaluated", message: payload.message, execution_claim: "not_run",
    assistance_kind: payload.assistance_kind, score_breakdown: scoreBreakdown, finding_feedback: parsed,
    omission_band: payload.omission_band, next_action: payload.next_action,
  };
}

function toModelReviewScoreBreakdown(payload: unknown): ModelReviewScoreBreakdown | null {
  const keys = ["policy_version", "verdict", "discovery", "omission", "severity", "evidence", "validation_method", "suggested_fix", "false_positive", "duplicate"];
  if (!isRecord(payload) || !hasExactKeys(payload, keys) || payload.policy_version !== "model_code_review_score_v1") return null;
  if (!keys.slice(1).every((key) => isScore(payload[key]))) return null;
  return {
    policy_version: "model_code_review_score_v1",
    verdict: Number(payload.verdict), discovery: Number(payload.discovery), omission: Number(payload.omission),
    severity: Number(payload.severity), evidence: Number(payload.evidence),
    validation_method: Number(payload.validation_method), suggested_fix: Number(payload.suggested_fix),
    false_positive: Number(payload.false_positive), duplicate: Number(payload.duplicate),
  };
}

function toModelReviewFindingFeedback(payload: unknown): ModelReviewFindingFeedback | null {
  if (
    !isRecord(payload) || !hasExactKeys(payload, ["client_finding_id", "status", "safe_reason_code"]) ||
    !isString(payload.client_finding_id) || !isModelReviewFindingStatus(payload.status) || !isString(payload.safe_reason_code)
  ) return null;
  return { client_finding_id: payload.client_finding_id, status: payload.status, safe_reason_code: payload.safe_reason_code };
}

function toExerciseAttemptState(payload: unknown): ExerciseAttemptState | null {
  if (!isRecord(payload)) return null;
  const baseKeys = [
    "attempt_id", "attempt_type", "track_id", "knowledge_key", "exercise_version_id", "submission_hash",
    "independence", "assistance_kind", "accepted_at", "status", "execution_job_id", "execution_job_state", "result", "projected",
    "route_changed", "mastery", "idempotent_replayed",
  ];
  const withTierKeys = [...baseKeys, "execution_tier", "execution_disclosure"];
  if (!hasExactKeys(payload, baseKeys) && !hasExactKeys(payload, withTierKeys)) return null;
  if (
    !isString(payload.attempt_id) || !isExerciseAttemptType(payload.attempt_type) ||
    !isString(payload.track_id) || !isString(payload.knowledge_key) || !isString(payload.exercise_version_id) ||
    !isString(payload.submission_hash) || !isExerciseIndependence(payload.independence) ||
    !isModelReviewAssistanceKind(payload.assistance_kind) || !isNullableString(payload.accepted_at) || (payload.status !== "pending" && payload.status !== "terminal") ||
    !isNullableString(payload.execution_job_id) || !isNullableString(payload.execution_job_state) ||
    !(payload.projected === null || typeof payload.projected === "boolean") ||
    typeof payload.route_changed !== "boolean" || typeof payload.idempotent_replayed !== "boolean"
  ) return null;
  const result = payload.result === null ? null : toLessonGateResult(payload.result);
  if ((payload.result !== null && !result) || (payload.status === "terminal") !== (result !== null)) return null;
  const mastery = toExerciseMastery(payload.mastery);
  if (payload.mastery !== null && !mastery) return null;
  if (payload.execution_tier !== undefined && (!isExecutionTier(payload.execution_tier) || !isString(payload.execution_disclosure))) return null;
  return {
    attempt_id: payload.attempt_id,
    attempt_type: payload.attempt_type,
    track_id: payload.track_id,
    knowledge_key: payload.knowledge_key,
    exercise_version_id: payload.exercise_version_id,
    submission_hash: payload.submission_hash,
    independence: payload.independence,
    assistance_kind: payload.assistance_kind,
    accepted_at: payload.accepted_at,
    status: payload.status,
    execution_job_id: payload.execution_job_id,
    execution_job_state: payload.execution_job_state,
    result,
    projected: payload.projected,
    route_changed: payload.route_changed,
    mastery,
    idempotent_replayed: payload.idempotent_replayed,
    ...(payload.execution_tier !== undefined ? {
      execution_tier: payload.execution_tier,
      execution_disclosure: payload.execution_disclosure as string,
    } : {}),
  };
}

function toExerciseMastery(payload: unknown): ExerciseAttemptState["mastery"] | null {
  if (payload === null) return null;
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, ["confidence", "mastery_level", "evidence_count", "observation_count"]) ||
    !isScore(payload.confidence) || !isString(payload.mastery_level) ||
    !isNonNegativeSafeInteger(payload.evidence_count) || !isNonNegativeSafeInteger(payload.observation_count)
  ) return null;
  return {
    confidence: payload.confidence,
    mastery_level: payload.mastery_level,
    evidence_count: payload.evidence_count,
    observation_count: payload.observation_count,
  };
}

function toModuleDiagnosticState(payload: unknown): ModuleDiagnosticState | null {
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, [
      "session_id", "track_id", "module_key", "diagnostic_version", "policy_version", "core_capabilities",
      "pass_threshold", "require_all_core", "independent_only", "cooldown_seconds", "state", "version",
      "source_plan_revision_id", "proposed_plan_revision_id", "impact", "weak_capabilities", "started_at",
      "terminal_at", "cooldown_until", "confirmed_at", "items", "idempotent_replayed",
    ]) ||
    !isString(payload.session_id) || !isString(payload.track_id) || !isString(payload.module_key) ||
    !isString(payload.diagnostic_version) || !isString(payload.policy_version) || !isStringArray(payload.core_capabilities) ||
    !isScore(payload.pass_threshold) || typeof payload.require_all_core !== "boolean" ||
    typeof payload.independent_only !== "boolean" || !isNonNegativeSafeInteger(payload.cooldown_seconds) ||
    !isModuleDiagnosticState(payload.state) || !isNonNegativeSafeInteger(payload.version) ||
    !isString(payload.source_plan_revision_id) || !isNullableString(payload.proposed_plan_revision_id) ||
    !isStringArray(payload.weak_capabilities) || !isNullableString(payload.started_at) ||
    !isNullableString(payload.terminal_at) || !isNullableString(payload.cooldown_until) ||
    !isNullableString(payload.confirmed_at) || !Array.isArray(payload.items) ||
    typeof payload.idempotent_replayed !== "boolean"
  ) return null;
  const impact = toModuleDiagnosticImpact(payload.impact);
  if (impact === undefined) return null;
  const items = payload.items.map(toModuleDiagnosticItem);
  if (items.some((item) => item === null)) return null;
  return {
    session_id: payload.session_id,
    track_id: payload.track_id,
    module_key: payload.module_key,
    diagnostic_version: payload.diagnostic_version,
    policy_version: payload.policy_version,
    core_capabilities: payload.core_capabilities,
    pass_threshold: payload.pass_threshold,
    require_all_core: payload.require_all_core,
    independent_only: payload.independent_only,
    cooldown_seconds: payload.cooldown_seconds,
    state: payload.state,
    version: payload.version,
    source_plan_revision_id: payload.source_plan_revision_id,
    proposed_plan_revision_id: payload.proposed_plan_revision_id,
    impact,
    weak_capabilities: payload.weak_capabilities,
    started_at: payload.started_at,
    terminal_at: payload.terminal_at,
    cooldown_until: payload.cooldown_until,
    confirmed_at: payload.confirmed_at,
    items: items.filter((item): item is ModuleDiagnosticItem => item !== null),
    idempotent_replayed: payload.idempotent_replayed,
  };
}

function toModuleDiagnosticItem(payload: unknown): ModuleDiagnosticItem | null {
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, ["item_id", "item_key", "order_index", "capability_key", "knowledge_key", "threshold", "exercise", "attempt_id", "execution_job_state", "result"]) ||
    !isString(payload.item_id) || !isString(payload.item_key) || !isNonNegativeSafeInteger(payload.order_index) ||
    !isString(payload.capability_key) || !isString(payload.knowledge_key) || !isScore(payload.threshold) ||
    !isNullableString(payload.attempt_id) || !isNullableString(payload.execution_job_state)
  ) return null;
  const exercise = toLessonGateExercise(payload.exercise, false);
  const result = payload.result === null ? null : toLessonGateResult(payload.result);
  if (!exercise || (payload.result !== null && !result)) return null;
  return {
    item_id: payload.item_id,
    item_key: payload.item_key,
    order_index: payload.order_index,
    capability_key: payload.capability_key,
    knowledge_key: payload.knowledge_key,
    threshold: payload.threshold,
    exercise,
    attempt_id: payload.attempt_id,
    execution_job_state: payload.execution_job_state,
    result,
  };
}

function toModuleDiagnosticImpact(payload: unknown): ModuleDiagnosticImpact | null | undefined {
  if (!isRecord(payload)) return undefined;
  if (Object.keys(payload).length === 0) return null;
  if (
    !hasExactKeys(payload, ["kind", "module_key", "diagnostic_session_id", "policy_version", "affected_knowledge_keys", "capability_scores", "source_plan_revision_id", "proposed_plan_revision_id", "expected_track_version"]) ||
    payload.kind !== "diagnostic_skipped_module" || !isString(payload.module_key) ||
    !isString(payload.diagnostic_session_id) || !isString(payload.policy_version) ||
    !isStringArray(payload.affected_knowledge_keys) || !isString(payload.source_plan_revision_id) ||
    !isString(payload.proposed_plan_revision_id) || !isNonNegativeSafeInteger(payload.expected_track_version)
  ) return undefined;
  const scores = toScoreRecord(payload.capability_scores);
  if (!scores) return undefined;
  return {
    kind: "diagnostic_skipped_module",
    module_key: payload.module_key,
    diagnostic_session_id: payload.diagnostic_session_id,
    policy_version: payload.policy_version,
    affected_knowledge_keys: payload.affected_knowledge_keys,
    capability_scores: scores,
    source_plan_revision_id: payload.source_plan_revision_id,
    proposed_plan_revision_id: payload.proposed_plan_revision_id,
    expected_track_version: payload.expected_track_version,
  };
}

function toLessonDocument(payload: unknown): LessonDocument | null {
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, ["schema_version", "title", "language_id", "knowledge_key", "content_standard_version", "coverage_keys", "blocks", "content_hash"]) ||
    payload.schema_version !== "lesson_document_v1" || !isString(payload.title) ||
    !isString(payload.language_id) || !isString(payload.knowledge_key) ||
    !isString(payload.content_standard_version) || !isStringArray(payload.coverage_keys) ||
    !Array.isArray(payload.blocks) || !isString(payload.content_hash)
  ) return null;
  const blocks = payload.blocks.map(toLessonBlock);
  if (blocks.some((block) => block === null)) return null;
  const parsed = blocks.filter((block): block is LessonBlock => block !== null);
  if (
    new Set(parsed.map((block) => block.block_id)).size !== parsed.length ||
    parsed.some((block, index) => block.order_index !== index)
  ) return null;
  return {
    schema_version: "lesson_document_v1",
    title: payload.title,
    language_id: payload.language_id,
    knowledge_key: payload.knowledge_key,
    content_standard_version: payload.content_standard_version,
    coverage_keys: payload.coverage_keys,
    blocks: parsed,
    content_hash: payload.content_hash,
  };
}

function toLessonBlock(payload: unknown): LessonBlock | null {
  if (
    !isRecord(payload) || !isString(payload.block_id) ||
    !isNonNegativeSafeInteger(payload.order_index) || !isStringArray(payload.citation_ids) ||
    !isString(payload.type)
  ) return null;
  const base = { block_id: payload.block_id, order_index: payload.order_index, citation_ids: payload.citation_ids };
  switch (payload.type) {
    case "heading":
      if (!hasExactKeys(payload, ["block_id", "type", "order_index", "citation_ids", "title", "subtitle"]) || !isString(payload.title) || !isString(payload.subtitle)) return null;
      return { ...base, type: "heading", title: payload.title, subtitle: payload.subtitle };
    case "learning_objectives":
      if (!hasExactKeys(payload, ["block_id", "type", "order_index", "citation_ids", "items", "coverage_keys"]) || !isStringArray(payload.items) || !isStringArray(payload.coverage_keys)) return null;
      return { ...base, type: "learning_objectives", items: payload.items, coverage_keys: payload.coverage_keys };
    case "concept":
      if (!hasExactKeys(payload, ["block_id", "type", "order_index", "citation_ids", "title", "paragraphs", "coverage_keys"]) || !isString(payload.title) || !isStringArray(payload.paragraphs) || !isStringArray(payload.coverage_keys)) return null;
      return { ...base, type: "concept", title: payload.title, paragraphs: payload.paragraphs, coverage_keys: payload.coverage_keys };
    case "authority_note":
      if (!hasExactKeys(payload, ["block_id", "type", "order_index", "citation_ids", "title", "statement"]) || !isString(payload.title) || !isString(payload.statement)) return null;
      return { ...base, type: "authority_note", title: payload.title, statement: payload.statement };
    case "code_example":
      if (!hasExactKeys(payload, ["block_id", "type", "order_index", "citation_ids", "title", "language_id", "code", "explanation", "execution_claim"]) || !isString(payload.title) || !isString(payload.language_id) || !isString(payload.code) || !isStringArray(payload.explanation) || payload.execution_claim !== "not_run") return null;
      return { ...base, type: "code_example", title: payload.title, language_id: payload.language_id, code: payload.code, explanation: payload.explanation, execution_claim: "not_run" };
    case "comparison":
      if (!hasExactKeys(payload, ["block_id", "type", "order_index", "citation_ids", "title", "columns", "rows", "conclusion"]) || !isString(payload.title) || !isStringArray(payload.columns) || !Array.isArray(payload.rows) || !payload.rows.every(isStringArray) || !isString(payload.conclusion)) return null;
      return { ...base, type: "comparison", title: payload.title, columns: payload.columns, rows: payload.rows, conclusion: payload.conclusion };
    case "hint":
      if (!hasExactKeys(payload, ["block_id", "type", "order_index", "citation_ids", "title", "steps"]) || !isString(payload.title) || !isStringArray(payload.steps)) return null;
      return { ...base, type: "hint", title: payload.title, steps: payload.steps };
    case "exercise_gate":
      if (!hasExactKeys(payload, ["block_id", "type", "order_index", "citation_ids", "gate_key", "gate_kind", "assessment_contract_version", "required_capabilities", "learner_prompt"]) || !isString(payload.gate_key) || !isLessonGateKind(payload.gate_kind) || !isString(payload.assessment_contract_version) || !isStringArray(payload.required_capabilities) || !isString(payload.learner_prompt)) return null;
      return { ...base, type: "exercise_gate", gate_key: payload.gate_key, gate_kind: payload.gate_kind, assessment_contract_version: payload.assessment_contract_version, required_capabilities: payload.required_capabilities, learner_prompt: payload.learner_prompt };
    case "summary":
      if (!hasExactKeys(payload, ["block_id", "type", "order_index", "citation_ids", "points", "coverage_keys"]) || !isStringArray(payload.points) || !isStringArray(payload.coverage_keys)) return null;
      return { ...base, type: "summary", points: payload.points, coverage_keys: payload.coverage_keys };
    case "next_steps":
      if (!hasExactKeys(payload, ["block_id", "type", "order_index", "citation_ids", "items"]) || !isStringArray(payload.items)) return null;
      return { ...base, type: "next_steps", items: payload.items };
    default:
      return null;
  }
}

function toLessonCitation(payload: unknown): LessonCitation | null {
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, ["citation_id", "source_id", "display_name", "provider", "trust_tier", "source_type", "source_version_label", "source_version_kind", "canonical_url", "section_path", "fetched_at", "snapshotted_at", "evidence_excerpt"]) ||
    !isString(payload.citation_id) || !isString(payload.source_id) || !isString(payload.display_name) ||
    !isString(payload.provider) || !isLessonTrustTier(payload.trust_tier) ||
    !isLessonSourceType(payload.source_type) || !isString(payload.source_version_label) ||
    !isLessonSourceVersionKind(payload.source_version_kind) || !isSafeHttpUrl(payload.canonical_url) ||
    !isStringArray(payload.section_path) || !isString(payload.fetched_at) ||
    !isString(payload.snapshotted_at) || !isString(payload.evidence_excerpt)
  ) return null;
  return {
    citation_id: payload.citation_id, source_id: payload.source_id,
    display_name: payload.display_name, provider: payload.provider,
    trust_tier: payload.trust_tier, source_type: payload.source_type,
    source_version_label: payload.source_version_label,
    source_version_kind: payload.source_version_kind, canonical_url: payload.canonical_url,
    section_path: payload.section_path, fetched_at: payload.fetched_at,
    snapshotted_at: payload.snapshotted_at, evidence_excerpt: payload.evidence_excerpt,
  };
}

function toLessonAssignment(payload: unknown): LessonAssignment | null {
  if (
    !isRecord(payload) || !isString(payload.assignment_id) || !isString(payload.document_id) ||
    !isNonNegativeSafeInteger(payload.assignment_version) || !isLessonAssignmentStatus(payload.status) ||
    !isString(payload.content_hash) || !isNullableString(payload.started_at) ||
    !isNullableString(payload.activated_at) ||
    !(payload.progress_status === undefined || isNullableString(payload.progress_status)) ||
    !(payload.progress_version === undefined || payload.progress_version === null || isNonNegativeSafeInteger(payload.progress_version))
  ) return null;
  const allowed = ["assignment_id", "document_id", "assignment_version", "status", "content_hash", "started_at", "activated_at", "progress_status", "progress_version"];
  if (!Object.keys(payload).every((key) => allowed.includes(key))) return null;
  return {
    assignment_id: payload.assignment_id, document_id: payload.document_id,
    assignment_version: payload.assignment_version, status: payload.status,
    content_hash: payload.content_hash, started_at: payload.started_at,
    activated_at: payload.activated_at, progress_status: payload.progress_status ?? null,
    progress_version: payload.progress_version ?? null,
  };
}

function toLessonAuthoringRun(payload: unknown): LessonAuthoringRun | null {
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, ["run_id", "state", "run_kind", "attempt_count", "failure_code", "failure_message", "created_at", "updated_at", "terminal_at"]) ||
    !isString(payload.run_id) || !isLessonAuthoringState(payload.state) ||
    (payload.run_kind !== "prepare" && payload.run_kind !== "refresh") ||
    !isNonNegativeSafeInteger(payload.attempt_count) || !isNullableString(payload.failure_code) ||
    !isNullableString(payload.failure_message) || !isString(payload.created_at) ||
    !isString(payload.updated_at) || !isNullableString(payload.terminal_at)
  ) return null;
  return {
    run_id: payload.run_id, state: payload.state, run_kind: payload.run_kind,
    attempt_count: payload.attempt_count, failure_code: payload.failure_code,
    failure_message: payload.failure_message, created_at: payload.created_at,
    updated_at: payload.updated_at, terminal_at: payload.terminal_at,
  };
}

function toLessonUpdateProposal(payload: unknown): LessonUpdateProposal | null {
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, ["assignment_id", "assignment_version", "document_id", "status", "impact"]) ||
    !isString(payload.assignment_id) || !isNonNegativeSafeInteger(payload.assignment_version) ||
    !isString(payload.document_id) || payload.status !== "proposed" || !isRecord(payload.impact)
  ) return null;
  const impact = payload.impact;
  const keys = ["source_changes", "blocks_added", "blocks_removed", "blocks_reordered", "examples_changed", "gates_changed", "retained_blocks"];
  if (
    !hasExactKeys(impact, keys) ||
    !isStringArray(impact.source_changes) || !isStringArray(impact.blocks_added) ||
    !isStringArray(impact.blocks_removed) || !isStringArray(impact.blocks_reordered) ||
    !isStringArray(impact.examples_changed) || !isStringArray(impact.gates_changed) ||
    !isStringArray(impact.retained_blocks)
  ) return null;
  return {
    assignment_id: payload.assignment_id, assignment_version: payload.assignment_version,
    document_id: payload.document_id, status: "proposed",
    impact: {
      source_changes: impact.source_changes, blocks_added: impact.blocks_added,
      blocks_removed: impact.blocks_removed, blocks_reordered: impact.blocks_reordered,
      examples_changed: impact.examples_changed, gates_changed: impact.gates_changed,
      retained_blocks: impact.retained_blocks,
    },
  };
}

function isLessonPublicStatus(value: unknown): value is LessonDocumentState["status"] {
  return value === "missing" || value === "preparing" || value === "ready" || value === "failed";
}
function isLessonAssignmentStatus(value: unknown): value is LessonAssignment["status"] {
  return value === "active" || value === "proposed" || value === "superseded";
}
function isLessonAuthoringState(value: unknown): value is LessonAuthoringRun["state"] {
  return value === "pending" || value === "claimed" || value === "running" || value === "completed" || value === "failed" || value === "cancelled";
}
function isLessonGateKind(value: unknown): value is "knowledge_check" | "guided_practice" | "independent_practice" {
  return value === "knowledge_check" || value === "guided_practice" || value === "independent_practice";
}
function isLessonTrustTier(value: unknown): value is LessonCitation["trust_tier"] {
  return value === "official" || value === "trusted_de_facto" || value === "internal";
}
function isLessonSourceType(value: unknown): value is LessonCitation["source_type"] {
  return value === "tutorial" || value === "reference" || value === "spec" || value === "platform_docs" || value === "vendor_docs";
}
function isLessonSourceVersionKind(value: unknown): value is LessonCitation["source_version_kind"] {
  return value === "fixed" || value === "rolling";
}
function isSafeHttpUrl(value: unknown): value is string {
  if (!isString(value)) return false;
  try {
    const parsed = new URL(value);
    return (parsed.protocol === "http:" || parsed.protocol === "https:") && !parsed.username && !parsed.password;
  } catch {
    return false;
  }
}
function hasExactKeys(value: Record<string, unknown>, expected: string[]): boolean {
  const keys = Object.keys(value).sort();
  return keys.length === expected.length && keys.every((key, index) => key === [...expected].sort()[index]);
}

function hasRequiredAndOptionalKeys(value: Record<string, unknown>, required: string[], optional: string[]): boolean {
  const allowed = new Set([...required, ...optional]);
  const keys = Object.keys(value);
  return required.every((key) => keys.includes(key)) && keys.every((key) => allowed.has(key));
}

function toLearningLanguageCatalogItem(payload: unknown): LearningLanguageCatalogItem | null {
  if (
    !isRecord(payload) ||
    !isString(payload.language_id) ||
    !isString(payload.display_name) ||
    !isSelectionTier(payload.selection_tier) ||
    typeof payload.selectable !== "boolean" ||
    !isCapabilityState(payload.lesson_generation_state) ||
    !isExecutionTier(payload.execution_tier) ||
    !isString(payload.execution_disclosure) ||
    !isSourceTrustPolicy(payload.source_trust_policy)
  ) return null;
  return payload as LearningLanguageCatalogItem;
}

function toLearningPlanSession(payload: unknown): LearningPlanSession | null {
  if (
    !isRecord(payload) ||
    !isString(payload.session_id) ||
    !isString(payload.conversation_id) ||
    !isLearningPlanSessionStatus(payload.status) ||
    !isNullableString(payload.preferred_language_id) ||
    !isNonNegativeSafeInteger(payload.version) ||
    !isNullableString(payload.confirmed_track_id) ||
    !isNullableString(payload.created_at) ||
    !isNullableString(payload.updated_at) ||
    !isNullableString(payload.confirmed_at) ||
    !isNullableString(payload.cancelled_at)
  ) return null;
  const draft = payload.current_draft === null ? null : toLearningPlanDraft(payload.current_draft);
  if (draft === null && payload.current_draft !== null) return null;
  const lastError = payload.last_error;
  let parsedLastError: LearningPlanSession["last_error"] = null;
  if (lastError !== null) {
    if (!isRecord(lastError) || !isString(lastError.code) || !isNullableString(lastError.at)) return null;
    parsedLastError = { code: lastError.code, at: lastError.at };
  }
  return {
    session_id: payload.session_id,
    conversation_id: payload.conversation_id,
    status: payload.status,
    preferred_language_id: payload.preferred_language_id,
    version: payload.version,
    current_draft: draft,
    confirmed_track_id: payload.confirmed_track_id,
    last_error: parsedLastError,
    created_at: payload.created_at,
    updated_at: payload.updated_at,
    confirmed_at: payload.confirmed_at,
    cancelled_at: payload.cancelled_at,
  };
}

function toLearningPlanDraft(payload: unknown): LearningPlanDraft | null {
  if (
    !isRecord(payload) ||
    !isString(payload.draft_id) ||
    !isNonNegativeSafeInteger(payload.draft_version) ||
    !isString(payload.content_hash) ||
    !isString(payload.generator_version) ||
    !isString(payload.policy_version) ||
    !isNullableString(payload.created_at) ||
    !Array.isArray(payload.sources)
  ) return null;
  const profile = toLearningPlanProfile(payload.profile);
  if (!profile || !isRecord(payload.plan) || !isString(payload.plan.title) || !isString(payload.plan.target_level) || !Array.isArray(payload.plan.modules)) return null;
  const modules = payload.plan.modules.map(toLearningPlanModule);
  if (modules.some((module) => module === null)) return null;
  const sources: LearningPlanDraft["sources"] = [];
  for (const source of payload.sources) {
    if (!isRecord(source) || !isString(source.source_id) || !isString(source.display_name) || !isString(source.trust_tier)) return null;
    sources.push({ source_id: source.source_id, display_name: source.display_name, trust_tier: source.trust_tier });
  }
  return {
    draft_id: payload.draft_id,
    draft_version: payload.draft_version,
    content_hash: payload.content_hash,
    profile,
    plan: {
      title: payload.plan.title,
      target_level: payload.plan.target_level,
      modules: modules.filter((module): module is LearningPlanModule => module !== null),
    },
    sources,
    generator_version: payload.generator_version,
    policy_version: payload.policy_version,
    created_at: payload.created_at,
  };
}

function toLearningPlanProfile(payload: unknown): LearningPlanProfile | null {
  if (
    !isRecord(payload) ||
    !isString(payload.language_id) ||
    !isString(payload.goal_text) ||
    !isString(payload.target_level) ||
    !isNonNegativeSafeInteger(payload.weekly_minutes) ||
    !isExperienceLevel(payload.experience_level) ||
    !isStringArray(payload.teaching_preferences) ||
    !isString(payload.pace_summary) ||
    !isString(payload.title)
  ) return null;
  return payload as LearningPlanProfile;
}

function toLearningPlanModule(payload: unknown): LearningPlanModule | null {
  if (
    !isRecord(payload) ||
    !isString(payload.module_key) ||
    !isString(payload.title) ||
    !isString(payload.description) ||
    !isNonNegativeSafeInteger(payload.order_index) ||
    typeof payload.is_core !== "boolean" ||
    typeof payload.is_skippable !== "boolean" ||
    !Array.isArray(payload.nodes)
  ) return null;
  const nodes = payload.nodes.map(toLearningPlanNode);
  if (nodes.some((node) => node === null)) return null;
  return {
    module_key: payload.module_key,
    title: payload.title,
    description: payload.description,
    order_index: payload.order_index,
    is_core: payload.is_core,
    is_skippable: payload.is_skippable,
    nodes: nodes.filter((node): node is LearningPlanNode => node !== null),
  };
}

function toLearningPlanNode(payload: unknown): LearningPlanNode | null {
  if (
    !isRecord(payload) ||
    !isString(payload.knowledge_key) ||
    !isString(payload.title) ||
    !isString(payload.description) ||
    !isNonNegativeSafeInteger(payload.order_index) ||
    typeof payload.is_core !== "boolean" ||
    !isStringArray(payload.prerequisite_keys) ||
    !isStringArray(payload.required_capabilities)
  ) return null;
  return payload as LearningPlanNode;
}

function isLearningTrackStatus(value: unknown): value is LearningTrackSummary["status"] {
  return value === "active" || value === "paused" || value === "completed" || value === "archived";
}

function isExecutionTier(value: unknown): value is ExecutionTier {
  return value === "teaching_local" || value === "container_verified" || value === "static_only" || value === "unavailable";
}

function isModelReviewAuthoringState(value: unknown): value is ModelReviewAuthoringRun["state"] {
  return value === "pending" || value === "claimed" || value === "running" || value === "validating" || value === "completed" || value === "failed" || value === "cancelled";
}

function isVisibleEvidenceCheckType(value: unknown): value is ModelReviewVisibleEvidence["checks"][number]["check_type"] {
  return value === "parser" || value === "compile_or_typecheck" || value === "visible_tests" || value === "hidden_tests" || value === "coverage";
}

function isModelReviewFindingStatus(value: unknown): value is ModelReviewFindingFeedback["status"] {
  return value === "supported" || value === "partial" || value === "unsupported" || value === "duplicate";
}

function normalizedLineCount(value: string): number {
  const normalized = value.replace(/\r\n?/g, "\n");
  const lines = normalized.split("\n");
  return normalized.endsWith("\n") ? lines.length - 1 : lines.length;
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function isPositiveSafeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0;
}

function isExerciseType(value: unknown): value is LessonGateExercise["exercise_type"] {
  return value === "code_completion" || value === "sql_query" || value === "browser_preview" || value === "static_code_reasoning" || value === "model_code_review";
}

function isGateRequirementKind(value: unknown): value is "required" | "recommended" | "diagnostic" {
  return value === "required" || value === "recommended" || value === "diagnostic";
}

function isExecutionRequirement(value: unknown): value is "required" | "optional" | "forbidden" {
  return value === "required" || value === "optional" || value === "forbidden";
}

function isLessonGateState(value: unknown): value is "available" | "in_progress" | "passed" | "remediation_required" {
  return value === "available" || value === "in_progress" || value === "passed" || value === "remediation_required";
}

function isLessonGateAction(value: unknown): value is LessonGateAction {
  return value === "prepare" || value === "hint" || value === "run" || value === "submit";
}

function isExerciseAttemptType(value: unknown): value is ExerciseAttemptState["attempt_type"] {
  return value === "run" || value === "submit" || value === "diagnostic_submit";
}

function isExerciseAttemptOutcome(value: unknown): value is ExerciseAttemptOutcome {
  return value === "passed" || value === "failed" || value === "timed_out" || value === "cancelled" || value === "unavailable" || value === "invalid";
}

function isExerciseIndependence(value: unknown): value is ExerciseAttemptState["independence"] {
  return value === "independent" || value === "hinted" || value === "remediated";
}

function isModelReviewAssistanceKind(value: unknown): value is ExerciseAttemptState["assistance_kind"] {
  return isExerciseIndependence(value) || value === "validation_evidence_viewed";
}

function isModuleDiagnosticState(value: unknown): value is ModuleDiagnosticState["state"] {
  return value === "active" || value === "failed" || value === "passed_pending_confirmation" || value === "confirmed" || value === "expired";
}

function isScore(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
}

function toScoreRecord(value: unknown): Record<string, number> | null {
  if (!isRecord(value)) return null;
  const entries = Object.entries(value);
  if (entries.some(([key, score]) => key.length === 0 || !isScore(score))) return null;
  return Object.fromEntries(entries) as Record<string, number>;
}

function isLearningProgressStatus(value: unknown): value is LearningRoadmapNode["progress_status"] {
  return value === "locked" || value === "available" || value === "in_progress" || value === "completed" ||
    value === "review_due" || value === "diagnostic_skipped";
}

function isReviewRiskLevel(value: unknown): value is ReviewQueueItem["risk_level"] {
  return value === "low" || value === "normal" || value === "high" || value === "critical";
}

function isReviewSessionState(value: unknown): value is ReviewSession["state"] {
  return value === "blocked" || value === "active" || value === "ready_to_finalize" ||
    value === "finalized" || value === "cancelled";
}

function isReviewSessionStage(value: unknown): value is ReviewSession["stage"] {
  return value === "warmup" || value === "practice" || value === "final_summary";
}

function isReviewRating(value: unknown): value is NonNullable<ReviewSession["finalization"]>["rating"] {
  return value === "again" || value === "hard" || value === "good" || value === "easy";
}

function isSelectionTier(value: unknown): value is LearningLanguageCatalogItem["selection_tier"] {
  return value === "core" || value === "extended" || value === "degraded" || value === "unavailable";
}

function isCapabilityState(value: unknown): value is LearningLanguageCatalogItem["lesson_generation_state"] {
  return value === "full" || value === "partial" || value === "planned" || value === "unsupported";
}

function isSourceTrustPolicy(value: unknown): value is LearningLanguageCatalogItem["source_trust_policy"] {
  return value === "official" || value === "trusted_de_facto" || value === "internal";
}

function isLearningPlanSessionStatus(value: unknown): value is LearningPlanSession["status"] {
  return value === "collecting" || value === "draft_ready" || value === "confirmed" || value === "cancelled";
}

function isExperienceLevel(value: unknown): value is LearningPlanProfile["experience_level"] {
  return value === "new" || value === "beginner" || value === "intermediate" || value === "advanced";
}

function toTutorConversationResponse(payload: unknown): TutorConversationResponse | null {
  if (
    !isRecord(payload) || !hasExactKeys(payload, ["conversation_id", "created", "idempotent_replayed"]) ||
    !isString(payload.conversation_id) || typeof payload.created !== "boolean" ||
    typeof payload.idempotent_replayed !== "boolean"
  ) return null;
  return { conversation_id: payload.conversation_id, created: payload.created, idempotent_replayed: payload.idempotent_replayed };
}

function toTutorContextReferences(payload: unknown): TutorContextReference[] | null {
  if (!Array.isArray(payload) || payload.length > 6) return null;
  const parsed = payload.map(toTutorContextReference);
  if (parsed.some((item) => item === null)) return null;
  return parsed.filter((item): item is TutorContextReference => item !== null);
}

function toTutorContextReference(payload: unknown): TutorContextReference | null {
  if (!isRecord(payload) || payload.schema_version !== "tutor_context_reference_v1" || !isString(payload.kind)) return null;
  const baseKeys = [
    "reference_id", "schema_version", "kind", "learning_track_id", "knowledge_key", "source_version",
    "source_hash", "safe_payload_hash", "created_at",
  ];
  if (
    !isString(payload.reference_id) || !isString(payload.learning_track_id) || !isString(payload.knowledge_key) ||
    !isString(payload.source_version) || !isSha256(payload.source_hash) || !isSha256(payload.safe_payload_hash) ||
    !isNullableString(payload.created_at)
  ) return null;
  const base = {
    reference_id: payload.reference_id, schema_version: "tutor_context_reference_v1" as const,
    learning_track_id: payload.learning_track_id, knowledge_key: payload.knowledge_key,
    source_version: payload.source_version, source_hash: payload.source_hash,
    safe_payload_hash: payload.safe_payload_hash, created_at: payload.created_at,
  };
  if (payload.kind === "lesson_selection") {
    if (
      !hasExactKeys(payload, [...baseKeys, "document_id", "document_content_hash", "content_standard_version", "assignment_version", "block_id", "start_offset", "end_offset", "safe_excerpt"]) ||
      !isString(payload.document_id) || !isSha256(payload.document_content_hash) || !isString(payload.content_standard_version) ||
      !isPositiveSafeInteger(payload.assignment_version) || !isString(payload.block_id) ||
      !isNonNegativeSafeInteger(payload.start_offset) || !isPositiveSafeInteger(payload.end_offset) ||
      payload.end_offset <= payload.start_offset || !isString(payload.safe_excerpt)
    ) return null;
    return { ...base, kind: "lesson_selection", document_id: payload.document_id,
      document_content_hash: payload.document_content_hash, content_standard_version: payload.content_standard_version,
      assignment_version: payload.assignment_version, block_id: payload.block_id, start_offset: payload.start_offset,
      end_offset: payload.end_offset, safe_excerpt: payload.safe_excerpt };
  }
  const feedbackKeys = [
    ...baseKeys, "attempt_id", "exercise_version_id", "outcome", "score", "assistance_kind",
    "feedback_summary", "capability_scores", "terminal_at",
  ];
  if (payload.kind === "exercise_feedback" || payload.kind === "execution_result") {
    const expected = payload.kind === "exercise_feedback"
      ? [...feedbackKeys, "attempt_type"]
      : [...feedbackKeys, "attempt_type", "execution_job_id", "execution_job_state"];
    const scores = toScoreRecord(payload.capability_scores);
    if (
      !hasExactKeys(payload, expected) || !isString(payload.attempt_id) ||
      (payload.attempt_type !== "run" && payload.attempt_type !== "submit") ||
      !isString(payload.exercise_version_id) || !isExerciseAttemptOutcome(payload.outcome) || !isScore(payload.score) ||
      !isModelReviewAssistanceKind(payload.assistance_kind) || !isString(payload.feedback_summary) || !scores ||
      !isNullableString(payload.terminal_at)
    ) return null;
    const attemptType: "run" | "submit" = payload.attempt_type;
    const feedback = { ...base, attempt_id: payload.attempt_id, attempt_type: attemptType,
      exercise_version_id: payload.exercise_version_id, outcome: payload.outcome, score: payload.score,
      assistance_kind: payload.assistance_kind, feedback_summary: payload.feedback_summary,
      capability_scores: scores, terminal_at: payload.terminal_at };
    if (payload.kind === "exercise_feedback") return { ...feedback, kind: "exercise_feedback" };
    if (!isString(payload.execution_job_id) || !isString(payload.execution_job_state)) return null;
    return { ...feedback, kind: "execution_result", execution_job_id: payload.execution_job_id,
      execution_job_state: payload.execution_job_state };
  }
  if (payload.kind === "review_feedback") {
    const scores = toScoreRecord(payload.capability_scores);
    if (
      !hasExactKeys(payload, [...feedbackKeys, "review_session_id", "review_item_id", "session_version"]) ||
      !isString(payload.review_session_id) || !isString(payload.review_item_id) || !isString(payload.attempt_id) ||
      !isString(payload.exercise_version_id) || !isPositiveSafeInteger(payload.session_version) ||
      !isExerciseAttemptOutcome(payload.outcome) || !isScore(payload.score) ||
      !isModelReviewAssistanceKind(payload.assistance_kind) || !isString(payload.feedback_summary) || !scores ||
      !isNullableString(payload.terminal_at)
    ) return null;
    return { ...base, kind: "review_feedback", review_session_id: payload.review_session_id,
      review_item_id: payload.review_item_id, attempt_id: payload.attempt_id,
      exercise_version_id: payload.exercise_version_id, session_version: payload.session_version,
      outcome: payload.outcome, score: payload.score, assistance_kind: payload.assistance_kind,
      feedback_summary: payload.feedback_summary, capability_scores: scores, terminal_at: payload.terminal_at };
  }
  return null;
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
    const legacyKeys = ["kind", "id", "role", "content", "public_thinking_steps", "context_references", "in_reply_to_item_id", "created_at"];
    const snapshotV2Keys = ["kind", "id", "turn_id", "role", "content", "public_thinking_text", "public_thinking_steps", "context_references", "in_reply_to_item_id", "created_at"];
    const snapshotV3Keys = ["kind", "id", "turn_id", "role", "content", "public_thinking_text", "public_thinking_steps", "runtime_output", "context_references", "in_reply_to_item_id", "created_at"];
    const legacy = hasExactKeys(payload, legacyKeys);
    const snapshotV2 = hasExactKeys(payload, snapshotV2Keys);
    const snapshotV3 = hasExactKeys(payload, snapshotV3Keys);
    if (!legacy && !snapshotV2 && !snapshotV3) return null;
    if ((payload.role !== "learner" && payload.role !== "tutor") || !isString(payload.content) ||
        !isStringArray(payload.public_thinking_steps) || !isNullableString(payload.in_reply_to_item_id) ||
        (!legacy && (!isNullableString(payload.turn_id) || !isString(payload.public_thinking_text)))) return null;
    if (payload.public_thinking_steps.length > 4 || payload.public_thinking_steps.some((step) => step.length === 0 || step.length > 320)) return null;
    const publicThinkingText: string = legacy
      ? payload.public_thinking_steps.join("\n\n")
      : String(payload.public_thinking_text);
    const turnId: string | null = legacy ? null : (payload.turn_id === null ? null : String(payload.turn_id));
    if (publicThinkingText.length > 1280) return null;
    const contextReferences = toTutorContextReferences(payload.context_references);
    const runtimeOutput = snapshotV3 && payload.runtime_output !== null
      ? toTutorRuntimeOutput(payload.runtime_output)
      : null;
    if (!contextReferences || (payload.role === "tutor" && contextReferences.length > 0) ||
        (snapshotV3 && payload.runtime_output !== null && runtimeOutput === null) ||
        (payload.role === "learner" && runtimeOutput !== null)) return null;
    return {
      kind: "message",
      id: payload.id,
      turn_id: turnId,
      role: payload.role,
      content: payload.content,
      public_thinking_text: payload.role === "tutor" ? publicThinkingText : "",
      public_thinking_steps: payload.role === "tutor" ? payload.public_thinking_steps : [],
      runtime_output: payload.role === "tutor" ? runtimeOutput : null,
      context_references: contextReferences,
      in_reply_to_item_id: payload.in_reply_to_item_id,
      created_at: payload.created_at,
    };
  }
  if (payload.kind === "process") {
    return toTutorPublicProcess(payload);
  }
  if (payload.kind === "error") {
    if (!hasExactKeys(payload, ["kind", "id", "turn_id", "code", "message", "recoverable", "created_at"]) ||
        !isNullableString(payload.turn_id) || !isString(payload.code) || !isString(payload.message) ||
        typeof payload.recoverable !== "boolean") return null;
    return {
      kind: "error", id: payload.id, turn_id: payload.turn_id, code: payload.code,
      message: payload.message, recoverable: payload.recoverable, created_at: payload.created_at,
    };
  }
  if (payload.kind === "elicitation" || payload.kind === "approval") {
    return toTutorInteractionRequestItem(payload);
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
  if (
    !isRecord(payload) || !hasExactKeys(payload, [
      "conversation_id", "run_id", "input_revision", "message_id", "event_cursor", "dispatch_job_id", "merged", "input_replayed",
      "idempotent_replayed", "run", "process", "replaced_run_id", "replaced_process", "context_references",
    ]) || !isString(payload.conversation_id) || !isString(payload.run_id) ||
    !isPositiveSafeInteger(payload.input_revision) || !isString(payload.message_id) ||
    !isNonNegativeSafeInteger(payload.event_cursor) || !isNullableString(payload.dispatch_job_id) || typeof payload.merged !== "boolean" ||
    typeof payload.input_replayed !== "boolean" || typeof payload.idempotent_replayed !== "boolean"
  ) return null;
  const run = toTutorRunState(payload.run);
  const process = payload.process === null ? null : toTutorPublicProcess(payload.process);
  const replacedProcess = payload.replaced_process === null ? null : toTutorPublicProcess(payload.replaced_process);
  const contextReferences = toTutorContextReferences(payload.context_references);
  if (!run || !contextReferences || (process === null && payload.process !== null) ||
      (replacedProcess === null && payload.replaced_process !== null) || !isNullableString(payload.replaced_run_id)) return null;
  return {
    conversation_id: payload.conversation_id, run_id: payload.run_id, input_revision: payload.input_revision,
    message_id: payload.message_id, event_cursor: payload.event_cursor, dispatch_job_id: payload.dispatch_job_id, merged: payload.merged,
    input_replayed: payload.input_replayed, idempotent_replayed: payload.idempotent_replayed, run, process,
    replaced_run_id: payload.replaced_run_id, replaced_process: replacedProcess,
    context_references: contextReferences,
  };
}

function toTutorRunState(payload: unknown): TutorRunState | null {
  if (!isRecord(payload) || !isString(payload.run_id) || !isString(payload.conversation_id) || (payload.origin !== "interactive" && payload.origin !== "proactive") || !isTutorRunStatus(payload.status) || !isNonNegativeSafeInteger(payload.input_revision) || typeof payload.cancelled !== "boolean" || !isNonNegativeSafeInteger(payload.iteration_count) || !isNonNegativeSafeInteger(payload.model_call_count) || !isNonNegativeSafeInteger(payload.capability_call_count) || !isNonNegativeSafeInteger(payload.effect_count) || !isNullableTutorTerminalOutcome(payload.terminal_outcome) || !isNullableTutorContinuationKind(payload.continuation_kind) || !isTutorInteractionProtocolVersion(payload.interaction_protocol_version) || !isNullableString(payload.retry_of_turn_id) || !isNullableString(payload.retry_root_turn_id) || !isNullableString(payload.response_to_request_id) || !isNullableTutorCompletionReason(payload.completion_reason) || !isNullableString(payload.created_at) || !isNullableString(payload.updated_at)) return null;
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
    interaction_protocol_version: payload.interaction_protocol_version,
    retry_of_turn_id: payload.retry_of_turn_id,
    retry_root_turn_id: payload.retry_root_turn_id,
    response_to_request_id: payload.response_to_request_id,
    completion_reason: payload.completion_reason,
    created_at: payload.created_at,
    updated_at: payload.updated_at,
  };
}

function toTutorConversationInputResponse(payload: unknown): TutorConversationInputResponse | null {
  return toTutorInputAcceptedResponse(payload) ?? toTutorQueuedInputAcceptedResponse(payload);
}

function toTutorQueuedInputAcceptedResponse(payload: unknown): TutorConversationInputResponse | null {
  if (!isRecord(payload) || !hasExactKeys(payload, [
    "conversation_id", "queued", "queue_item", "control_version", "pending_count", "max_pending", "idempotent_replayed",
  ]) || !isString(payload.conversation_id) || payload.queued !== true ||
      !isPositiveSafeInteger(payload.control_version) || !isNonNegativeSafeInteger(payload.pending_count) ||
      !isPositiveSafeInteger(payload.max_pending) || typeof payload.idempotent_replayed !== "boolean") return null;
  const queueItem = toTutorQueuedInput(payload.queue_item);
  return queueItem ? {
    conversation_id: payload.conversation_id, queued: true, queue_item: queueItem,
    control_version: payload.control_version, pending_count: payload.pending_count, max_pending: payload.max_pending,
    idempotent_replayed: payload.idempotent_replayed,
  } : null;
}

function toTutorQueuedInput(payload: unknown): TutorQueuedInput | null {
  if (!isRecord(payload) || !hasExactKeys(payload, [
    "item_id", "state", "position", "version", "content", "created_at", "updated_at",
  ]) || !isString(payload.item_id) || !isTutorQueueItemState(payload.state) ||
      !isPositiveSafeInteger(payload.position) || !isPositiveSafeInteger(payload.version) || !isString(payload.content) ||
      !isString(payload.created_at) || !isString(payload.updated_at)) return null;
  return {
    item_id: payload.item_id, state: payload.state, position: payload.position, version: payload.version,
    content: payload.content, created_at: payload.created_at, updated_at: payload.updated_at,
  };
}

function toTutorQueueStateResponse(payload: unknown): TutorQueueStateResponse | null {
  if (!isRecord(payload)) return null;
  const required = [
    "conversation_id", "control_version", "control_state", "queue_paused", "queue_pause_reason",
    "pending_count", "max_pending", "items", "active_turn", "pending_request",
  ];
  const keys = Object.keys(payload);
  if (!required.every((key) => keys.includes(key)) ||
      keys.some((key) => !required.includes(key) && key !== "idempotent_replayed") ||
      !isString(payload.conversation_id) || !isPositiveSafeInteger(payload.control_version) ||
      !isTutorConversationControlState(payload.control_state) || typeof payload.queue_paused !== "boolean" ||
      !isTutorQueuePauseReason(payload.queue_pause_reason) || !isNonNegativeSafeInteger(payload.pending_count) ||
      !isPositiveSafeInteger(payload.max_pending) || !Array.isArray(payload.items) ||
      ("idempotent_replayed" in payload && typeof payload.idempotent_replayed !== "boolean")) return null;
  const items = payload.items.map(toTutorQueuedInput);
  const activeTurn = payload.active_turn === null ? null : toTutorPublicTurn(payload.active_turn);
  const pendingRequest = payload.pending_request === null ? null : toTutorInteractionRequestItem(payload.pending_request);
  if (items.some((item) => item === null) || (activeTurn === null && payload.active_turn !== null) ||
      (pendingRequest === null && payload.pending_request !== null)) return null;
  return {
    conversation_id: payload.conversation_id, control_version: payload.control_version,
    control_state: payload.control_state, queue_paused: payload.queue_paused, queue_pause_reason: payload.queue_pause_reason,
    pending_count: payload.pending_count, max_pending: payload.max_pending,
    items: items.filter((item): item is TutorQueuedInput => item !== null), active_turn: activeTurn,
    pending_request: pendingRequest,
    ...(typeof payload.idempotent_replayed === "boolean" ? { idempotent_replayed: payload.idempotent_replayed } : {}),
  };
}

function toTutorQueueMutationResponse(payload: unknown): { state: TutorQueueStateResponse; queue_item: TutorQueuedInput | null } | null {
  if (!isRecord(payload) || !("queue_item" in payload)) return null;
  const queueItem = toTutorQueuedInput(payload.queue_item);
  if (!queueItem) return null;
  const { queue_item: _queueItem, ...statePayload } = payload;
  const state = toTutorQueueStateResponse(statePayload);
  return state ? { state, queue_item: queueItem } : null;
}

function toTutorControlledTurnResponse(
  payload: unknown,
  requireQueueItem: boolean,
): { turn: TutorControlledTurnResponse; queue_item: TutorQueuedInput | null } | null {
  if (!isRecord(payload) || !isPositiveSafeInteger(payload.control_version)) return null;
  const allowedExtra = new Set(["control_version", ...(requireQueueItem ? ["queue_item"] : [])]);
  const turnKeys = [
    "conversation_id", "run_id", "input_revision", "message_id", "event_cursor", "dispatch_job_id", "merged",
    "input_replayed", "idempotent_replayed", "run", "process", "replaced_run_id", "replaced_process", "context_references",
  ];
  if (Object.keys(payload).some((key) => !turnKeys.includes(key) && !allowedExtra.has(key))) return null;
  const projected = Object.fromEntries(turnKeys.map((key) => [key, payload[key]]));
  const accepted = toTutorInputAcceptedResponse(projected);
  const queueItem = requireQueueItem ? toTutorQueuedInput(payload.queue_item) : null;
  if (!accepted || (requireQueueItem && !queueItem)) return null;
  return { turn: { ...accepted, control_version: payload.control_version }, queue_item: queueItem };
}

function toTutorInteractionResponseAccepted(payload: unknown): TutorInteractionResponseAccepted | null {
  if (!isRecord(payload) || !hasExactKeys(payload, [
    "conversation_id", "run_id", "input_revision", "message_id", "event_cursor", "dispatch_job_id", "merged", "input_replayed",
    "idempotent_replayed", "run", "process", "replaced_run_id", "replaced_process", "context_references", "request", "response_replayed",
  ]) || typeof payload.response_replayed !== "boolean") return null;
  const request = toTutorInteractionRequestItem(payload.request);
  if (!request) return null;
  const accepted = toTutorInputAcceptedResponse({
    conversation_id: payload.conversation_id,
    run_id: payload.run_id,
    input_revision: payload.input_revision,
    message_id: payload.message_id,
    event_cursor: payload.event_cursor,
    dispatch_job_id: payload.dispatch_job_id,
    merged: payload.merged,
    input_replayed: payload.input_replayed,
    idempotent_replayed: payload.idempotent_replayed,
    run: payload.run,
    process: payload.process,
    replaced_run_id: payload.replaced_run_id,
    replaced_process: payload.replaced_process,
    context_references: payload.context_references,
  });
  return accepted ? { ...accepted, request, response_replayed: payload.response_replayed } : null;
}

function toTutorConversationSnapshotResponse(payload: unknown): TutorConversationSnapshotResponse | null {
  if (!isRecord(payload) || (payload.snapshot_version !== "tutor_conversation_snapshot_v2" && payload.snapshot_version !== "tutor_conversation_snapshot_v3")) return null;
  const version = payload.snapshot_version;
  const expectedKeys = version === "tutor_conversation_snapshot_v3"
    ? ["snapshot_version", "conversation", "active_turn", "active_thinking", "active_runtime_output", "pending_requests", "queue", "timeline", "next_cursor", "has_more", "stream_cursor"]
    : ["snapshot_version", "conversation", "active_turn", "active_thinking", "pending_requests", "queue", "timeline", "next_cursor", "has_more", "stream_cursor"];
  if (!hasExactKeys(payload, expectedKeys) || !isRecord(payload.conversation) ||
      !hasExactKeys(payload.conversation, [
        "conversation_id", "title", "control_version", "control_state", "queue_paused",
        "queue_pause_reason", "pending_count", "max_pending",
      ]) || !isString(payload.conversation.conversation_id) || !isString(payload.conversation.title) ||
      !isPositiveSafeInteger(payload.conversation.control_version) ||
      !isTutorConversationControlState(payload.conversation.control_state) ||
      typeof payload.conversation.queue_paused !== "boolean" || !isTutorQueuePauseReason(payload.conversation.queue_pause_reason) ||
      !isNonNegativeSafeInteger(payload.conversation.pending_count) || !isPositiveSafeInteger(payload.conversation.max_pending) ||
      !Array.isArray(payload.pending_requests) || !Array.isArray(payload.queue) || !Array.isArray(payload.timeline) ||
      !isNullableString(payload.next_cursor) || typeof payload.has_more !== "boolean" || !isString(payload.stream_cursor)) return null;
  const pendingRequests = payload.pending_requests.map(toTutorInteractionRequestItem);
  const queue = payload.queue.map(toTutorQueuedInput);
  const timeline = payload.timeline.map(toTutorHistoryItem);
  if (pendingRequests.some((item) => item === null) || queue.some((item) => item === null) || timeline.some((item) => item === null)) return null;
  const activeTurn = payload.active_turn === null ? null : toTutorPublicTurn(payload.active_turn);
  const activeThinking = payload.active_thinking === null ? null : toTutorActiveThinking(payload.active_thinking);
  const activeRuntimeOutput = version === "tutor_conversation_snapshot_v3" && payload.active_runtime_output !== null
    ? toTutorRuntimeOutput(payload.active_runtime_output)
    : null;
  if ((activeTurn === null && payload.active_turn !== null) ||
      (activeThinking === null && payload.active_thinking !== null) ||
      (version === "tutor_conversation_snapshot_v3" && payload.active_runtime_output !== null && activeRuntimeOutput === null) ||
      (activeThinking !== null && (activeTurn === null || activeThinking.turn_id !== activeTurn.turn_id || activeThinking.input_revision !== activeTurn.input_revision)) ||
      (activeRuntimeOutput !== null && (activeTurn === null || activeRuntimeOutput.input_revision !== activeTurn.input_revision))) return null;
  return {
    snapshot_version: version,
    conversation: {
      conversation_id: payload.conversation.conversation_id,
      title: payload.conversation.title,
      control_version: payload.conversation.control_version,
      control_state: payload.conversation.control_state,
      queue_paused: payload.conversation.queue_paused,
      queue_pause_reason: payload.conversation.queue_pause_reason,
      pending_count: payload.conversation.pending_count,
      max_pending: payload.conversation.max_pending,
    },
    active_turn: activeTurn,
    active_thinking: activeThinking,
    active_runtime_output: activeRuntimeOutput,
    pending_requests: pendingRequests.filter((item): item is TutorInteractionRequestItem => item !== null),
    queue: queue.filter((item): item is TutorQueuedInput => item !== null),
    timeline: timeline.filter((item): item is TutorHistoryItem => item !== null),
    next_cursor: payload.next_cursor,
    has_more: payload.has_more,
    stream_cursor: payload.stream_cursor,
  };
}

function toTutorRuntimeOutput(payload: unknown): TutorConversationSnapshotResponse["active_runtime_output"] {
  if (!isRecord(payload) || !hasExactKeys(payload, [
    "output_version", "input_revision", "generation", "reasoning_items", "final_answer_item",
  ]) || payload.output_version !== "tutor_runtime_output_v1" ||
      !isNonNegativeSafeInteger(payload.input_revision) || !isPositiveSafeInteger(payload.generation) ||
      !Array.isArray(payload.reasoning_items) || payload.reasoning_items.length > 64) return null;
  const reasoningItems = payload.reasoning_items.map(toTutorRuntimeOutputItem);
  const finalAnswerItem = payload.final_answer_item === null ? null : toTutorRuntimeOutputItem(payload.final_answer_item);
  if (reasoningItems.some((item) => item === null) || (payload.final_answer_item !== null && finalAnswerItem === null)) return null;
  return {
    output_version: "tutor_runtime_output_v1",
    input_revision: payload.input_revision,
    generation: payload.generation,
    reasoning_items: reasoningItems.filter((item): item is NonNullable<typeof item> => item !== null),
    final_answer_item: finalAnswerItem,
  };
}

function toTutorRuntimeOutputItem(payload: unknown) {
  if (!isRecord(payload) || !hasExactKeys(payload, ["item_id", "text", "state", "last_sequence"]) ||
      !isString(payload.item_id) || !isString(payload.text) || payload.text.length > 1_000_000 ||
      (payload.state !== "streaming" && payload.state !== "completed") ||
      !isNonNegativeSafeInteger(payload.last_sequence)) return null;
  return {
    item_id: payload.item_id,
    text: payload.text,
    state: payload.state,
    last_sequence: payload.last_sequence,
  } as const;
}

function toTutorActiveThinking(payload: unknown): TutorConversationSnapshotResponse["active_thinking"] {
  if (!isRecord(payload) || !hasExactKeys(payload, [
    "turn_id", "input_revision", "generation", "state", "text", "complete", "last_event_sequence",
  ]) || !isString(payload.turn_id) || !isNonNegativeSafeInteger(payload.input_revision) ||
      !isPositiveSafeInteger(payload.generation) || (payload.state !== "active" && payload.state !== "complete") ||
      !isString(payload.text) || payload.text.length > 1280 || typeof payload.complete !== "boolean" ||
      payload.complete !== (payload.state === "complete") || !isNonNegativeSafeInteger(payload.last_event_sequence)) return null;
  return {
    turn_id: payload.turn_id, input_revision: payload.input_revision, generation: payload.generation,
    state: payload.state, text: payload.text, complete: payload.complete,
    last_event_sequence: payload.last_event_sequence,
  };
}

function toTutorPublicTurn(payload: unknown): TutorConversationSnapshotResponse["active_turn"] {
  const required = ["turn_id", "conversation_id", "interaction_protocol_version", "status", "input_revision", "created_at", "updated_at"];
  const optional = ["retry_of_turn_id", "retry_root_turn_id", "completion_reason"];
  if (!isRecord(payload) || !hasRequiredAndOptionalKeys(payload, required, optional) ||
      !isString(payload.turn_id) || !isString(payload.conversation_id) || !isTutorInteractionProtocolVersion(payload.interaction_protocol_version) ||
      !isTutorPublicTurnStatus(payload.status) || !isNonNegativeSafeInteger(payload.input_revision) ||
      !(payload.retry_of_turn_id === undefined || isNullableString(payload.retry_of_turn_id)) ||
      !(payload.retry_root_turn_id === undefined || isNullableString(payload.retry_root_turn_id)) ||
      !(payload.completion_reason === undefined || isNullableTutorCompletionReason(payload.completion_reason)) ||
      !isNullableString(payload.created_at) || !isNullableString(payload.updated_at)) return null;
  return {
    turn_id: payload.turn_id, conversation_id: payload.conversation_id,
    interaction_protocol_version: payload.interaction_protocol_version, status: payload.status,
    input_revision: payload.input_revision, retry_of_turn_id: payload.retry_of_turn_id ?? null,
    retry_root_turn_id: payload.retry_root_turn_id ?? null, completion_reason: payload.completion_reason ?? null,
    created_at: payload.created_at, updated_at: payload.updated_at,
  };
}

function toTutorInteractionRequestItem(payload: unknown): TutorInteractionRequestItem | null {
  if (!isRecord(payload) || !hasExactKeys(payload, [
    "kind", "id", "request_id", "turn_id", "request_kind", "actor", "state", "version", "required", "prompt", "public_thinking_text", "presentation", "allowed_actions", "answer_turn_id", "created_at", "resolved_at",
  ]) || (payload.kind !== "elicitation" && payload.kind !== "approval") || !isString(payload.id) || !isString(payload.request_id) ||
      !isString(payload.turn_id) || !isTutorContinuationKind(payload.request_kind) ||
      (payload.actor !== "learner" && payload.actor !== "authority") || !isPositiveSafeInteger(payload.version) ||
      payload.required !== true || !isString(payload.prompt) || !isString(payload.public_thinking_text) || payload.public_thinking_text.length > 1280 || !Array.isArray(payload.allowed_actions) ||
      !isNullableString(payload.answer_turn_id) || !isNullableString(payload.created_at) || !isNullableString(payload.resolved_at)) return null;
  const presentation = toTutorRequestPresentation(payload.presentation);
  if (!presentation) return null;
  if (payload.kind === "approval") {
    if (payload.request_kind !== "approval" || payload.actor !== "learner" || presentation.type !== "approval" ||
        !isTutorApprovalState(payload.state) || !payload.allowed_actions.every((action) => action === "approve" || action === "deny")) return null;
    return {
      kind: "approval", id: payload.id, request_id: payload.request_id, turn_id: payload.turn_id,
      request_kind: "approval", actor: "learner", state: payload.state, version: payload.version,
      required: true, prompt: payload.prompt, public_thinking_text: payload.public_thinking_text, presentation, allowed_actions: payload.allowed_actions,
      answer_turn_id: payload.answer_turn_id, created_at: payload.created_at, resolved_at: payload.resolved_at,
    };
  }
  if (payload.request_kind === "approval" || !isTutorElicitationState(payload.state) ||
      !payload.allowed_actions.every((action) => action === "respond")) return null;
  return {
    kind: "elicitation", id: payload.id, request_id: payload.request_id, turn_id: payload.turn_id,
    request_kind: payload.request_kind, actor: payload.actor, state: payload.state, version: payload.version,
    required: true, prompt: payload.prompt, public_thinking_text: payload.public_thinking_text, presentation, allowed_actions: payload.allowed_actions,
    answer_turn_id: payload.answer_turn_id, created_at: payload.created_at, resolved_at: payload.resolved_at,
  };
}

function toTutorRequestPresentation(payload: unknown): TutorRequestPresentation | null {
  if (!isRecord(payload) || !isString(payload.type)) return null;
  if (payload.type === "text" && hasExactKeys(payload, ["type", "field_key", "minimum_length", "maximum_length", "multiline"]) &&
      isNullableString(payload.field_key) && isPositiveSafeInteger(payload.minimum_length) && isPositiveSafeInteger(payload.maximum_length) &&
      typeof payload.multiline === "boolean") return { type: "text", field_key: payload.field_key, minimum_length: payload.minimum_length, maximum_length: payload.maximum_length, multiline: payload.multiline };
  if (payload.type === "integer" && hasExactKeys(payload, ["type", "field_key", "minimum", "maximum", "step", "recommended", "unit"]) &&
      isString(payload.field_key) && typeof payload.minimum === "number" && typeof payload.maximum === "number" && isPositiveSafeInteger(payload.step) &&
      (payload.recommended === null || typeof payload.recommended === "number") && isString(payload.unit)) return { type: "integer", field_key: payload.field_key, minimum: payload.minimum, maximum: payload.maximum, step: payload.step, recommended: payload.recommended, unit: payload.unit };
  if ((payload.type === "single_select" || payload.type === "multi_select") && isString(payload.field_key) && Array.isArray(payload.options)) {
    const options = payload.options.map((option) => isRecord(option) && hasExactKeys(option, ["value", "label"]) && isString(option.value) && isString(option.label) ? { value: option.value, label: option.label } : null);
    if (options.some((option) => option === null)) return null;
    const validOptions = options.filter((option): option is { value: string; label: string } => option !== null);
    if (payload.type === "single_select" && hasExactKeys(payload, ["type", "field_key", "options", "recommended"]) && isNullableString(payload.recommended)) return { type: "single_select", field_key: payload.field_key, options: validOptions, recommended: payload.recommended };
    if (payload.type === "multi_select" && hasExactKeys(payload, ["type", "field_key", "options", "recommended", "maximum_selections"]) && isStringArray(payload.recommended) && isPositiveSafeInteger(payload.maximum_selections)) return { type: "multi_select", field_key: payload.field_key, options: validOptions, recommended: payload.recommended, maximum_selections: payload.maximum_selections };
  }
  if (payload.type === "approval" && hasExactKeys(payload, ["type", "proposal_id", "authority_key", "risk_level", "summary"]) &&
      isString(payload.proposal_id) && isString(payload.authority_key) && (payload.risk_level === "low" || payload.risk_level === "medium" || payload.risk_level === "high") && isString(payload.summary)) return { type: "approval", proposal_id: payload.proposal_id, authority_key: payload.authority_key, risk_level: payload.risk_level, summary: payload.summary };
  return null;
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

function isTutorContinuationKind(value: unknown): value is TutorContinuationKind {
  return value === "clarification" || value === "planning_input" || value === "approval" || value === "capability_result" || value === "external_result";
}

function isTutorInteractionProtocolVersion(value: unknown): value is "legacy_v1" | "thread_turn_v2" {
  return value === "legacy_v1" || value === "thread_turn_v2";
}

function isNullableTutorCompletionReason(value: unknown): value is "awaiting_user" | "awaiting_approval" | "awaiting_authority" | null {
  return value === null || value === "awaiting_user" || value === "awaiting_approval" || value === "awaiting_authority";
}

function isTutorConversationControlState(value: unknown): value is TutorQueueStateResponse["control_state"] {
  return value === "idle" || value === "running" || value === "waiting" || value === "queue_paused";
}

function isTutorQueuePauseReason(value: unknown): value is TutorQueueStateResponse["queue_pause_reason"] {
  return value === null || value === "pending_request" || value === "interrupted" || value === "failed";
}

function isTutorQueueItemState(value: unknown): value is TutorQueuedInput["state"] {
  return value === "pending" || value === "claimed" || value === "cancelled";
}

function isTutorPublicTurnStatus(value: unknown): value is "in_progress" | "completed" | "interrupted" | "failed" {
  return value === "in_progress" || value === "completed" || value === "interrupted" || value === "failed";
}

function isTutorElicitationState(value: unknown): value is "pending" | "answered" | "cancelled" | "expired" {
  return value === "pending" || value === "answered" || value === "cancelled" || value === "expired";
}

function isTutorApprovalState(value: unknown): value is "pending" | "answered" | "denied" | "cancelled" | "expired" {
  return value === "pending" || value === "answered" || value === "denied" || value === "cancelled" || value === "expired";
}

function isNullableTutorContinuationKind(value: unknown): value is TutorContinuationKind | null {
  return value === null || isTutorContinuationKind(value);
}

function isTutorProcessDisplayState(value: unknown): value is TutorPublicProcess["display_state"] {
  return value === "thinking" || value === "waiting_input" || value === "waiting_approval" || value === "waiting_authority" || value === "completed" || value === "interrupted" || value === "superseded" || value === "unavailable" || value === "failed";
}

function isTutorProcessStepKey(value: unknown): value is TutorPublicProcessStep["key"] {
  return value === "input_received" || value === "context_prepared" || value === "authorized_resource_checked" ||
    value === "runtime_started" || value === "domain_tool_running" || value === "domain_tool_completed" ||
    value === "learning_reply_generated" || value === "replaced_by_newer_input";
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
