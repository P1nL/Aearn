import type {
  ApiError,
  ApiHealth,
  HarnessCutoverDecision,
  TutorThreadTurnV2Capability,
  LanguageCourse,
  LessonAssignment,
  LessonAuthoringRun,
  LessonBlock,
  LessonCitation,
  LessonDocument,
  LessonDocumentState,
  LessonGateAction,
  LessonGateExercise,
  LessonGateHint,
  LessonGateItem,
  LessonGateList,
  LessonGatePrepareResponse,
  LessonGateResult,
  LessonPrepareResponse,
  ModelCodeReviewSubmission,
  ModelReviewArtifactV2,
  ModelReviewDiffHunkV2,
  ModelReviewDiffLineV2,
  ModelReviewErrorCategoryV2,
  ModelReviewArtifact,
  ModelReviewAuthoringRun,
  ModelReviewEvidenceResponse,
  ModelReviewFindingFeedback,
  ModelReviewPrompt,
  ModelReviewSafeFeedback,
  ModelReviewScoreBreakdown,
  ModelReviewVisibleEvidence,
  LessonUpdateProposal,
  ExerciseAttemptState,
  ExerciseAttemptOutcome,
  ExecutionTier,
  ModuleDiagnosticImpact,
  ModuleDiagnosticItem,
  ModuleDiagnosticState,
  LearningLanguageCatalogItem,
  LearningPlanDraft,
  LearningPlanModule,
  LearningPlanNode,
  LearningPlanProfile,
  LearningPlanSession,
  LearningScopeInput,
  LearningTrackSummary,
  LearningTrackDetail,
  LearningRoadmap,
  LearningRoadmapModule,
  LearningRoadmapNode,
  SafeExecutionLocation,
  SafeExecutionPresentation,
  SafeExecutionResultV2,
  SafeTestFeedbackV2,
  TutorActivityItem,
  TutorArtifactAction,
  TutorArtifactActionKind,
  TutorArtifactActionResponse,
  TutorArtifactAttemptDetail,
  TutorArtifactAttemptDetailV2,
  TutorArtifactAttemptResultV1,
  TutorArtifactAttemptResultV2,
  TutorArtifactAttemptSummary,
  TutorArtifactBranchSummary,
  TutorArtifactDifficulty,
  TutorArtifactKind,
  TutorArtifactOutcome,
  TutorArtifactOwnerKind,
  TutorArtifactPresentation,
  TutorArtifactPurpose,
  TutorArtifactSourceReference,
  TutorArtifactState,
  TutorBranchResponseDisposition,
  TutorContinuationKind,
  TutorConversationHistoryResponse,
  TutorConversationResponse,
  TutorConversationSnapshotResponse,
  TutorConversationInputResponse,
  TutorControlledTurnResponse,
  TutorContextReference,
  TutorContextReferenceDraft,
  TutorConversationListResponse,
  TutorConversationSummary,
  TutorForegroundRun,
  TutorHistoryItem,
  TutorInboxItem,
  TutorInteractionRequestItem,
  TutorInteractionResponseAccepted,
  TutorInteractionResponseDraft,
  TutorRequestPresentation,
  TutorInputAcceptedResponse,
  TutorMemoryItem,
  TutorPlanRevision,
  TutorPlanRevisionList,
  TutorPreferences,
  TutorPublicArtifactItem,
  TutorPublicBranchGroup,
  TutorPublicBranchItemReference,
  TutorPublicProcess,
  TutorPublicProcessStep,
  TutorQueuedInput,
  TutorQueueResumeResponse,
  TutorQueueStateResponse,
  TutorQueueSteerResponse,
  TutorRunState,
  TeachingActionDescriptor,
  TeachingActionShelf,
  TeachingCheckpointProjection,
  TeachingControlKey,
  TeachingFocusProjection,
  TeachingSessionActionResponse,
  TeachingSessionGroupProjection,
  TeachingSessionListResponse,
  TeachingSessionMode,
  TeachingSessionOpenResponse,
  TeachingSessionProjection,
  ReviewAttempt,
  ReviewHint,
  ReviewQueue,
  ReviewQueueItem,
  ReviewSession,
  ReviewSessionAttemptSummary,
  ReviewSessionItem,
  UserProfile,
} from "../types";

import {
  API_BASE_URL, hasExactKeys, hasRequiredAndOptionalKeys, isApiError, isNonNegativeSafeInteger,
  isNullableString, isRecord, isString, isStringArray, requestJson, tutorMutationHeaders,
} from "./client";

import {
  isExerciseAttemptOutcome, isModelReviewAssistanceKind, isPositiveSafeInteger, isScore, isSha256, toScoreRecord
} from "./learning";

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

export async function fetchTutorArtifact(input: {
  userId: string;
  conversationId: string;
  artifactId: string;
  signal?: AbortSignal;
}): Promise<TutorPublicArtifactItem> {
  const query = new URLSearchParams({ user_id: input.userId });
  const payload = await requestJson(
    `${API_BASE_URL}/api/tutor/conversations/${encodeURIComponent(input.conversationId)}/artifacts/${encodeURIComponent(input.artifactId)}?${query.toString()}`,
    { signal: input.signal },
  );
  const artifact = toTutorPublicArtifactItem(payload);
  if (!artifact || artifact.id !== input.artifactId || artifact.conversation_id !== input.conversationId) {
    throw new Error("Tutor Artifact API returned an invalid payload");
  }
  return artifact;
}

export async function fetchTutorArtifactAttempt(input: {
  userId: string;
  conversationId: string;
  artifactId: string;
  artifactVersion: number;
  learningTrackId: string;
  knowledgeKey: string;
  teachingSessionId: string;
  attemptId: string;
  signal?: AbortSignal;
}): Promise<TutorArtifactAttemptDetail> {
  const query = new URLSearchParams({ user_id: input.userId });
  const payload = await requestJson(
    `${API_BASE_URL}/api/tutor/conversations/${encodeURIComponent(input.conversationId)}/artifacts/${encodeURIComponent(input.artifactId)}/attempts/${encodeURIComponent(input.attemptId)}?${query.toString()}`,
    { signal: input.signal },
  );
  const attempt = toTutorArtifactAttemptDetail(payload);
  if (
    !attempt ||
    attempt.artifact_id !== input.artifactId ||
    attempt.artifact_version !== input.artifactVersion ||
    attempt.conversation_id !== input.conversationId ||
    attempt.learning_track_id !== input.learningTrackId ||
    attempt.knowledge_key !== input.knowledgeKey ||
    attempt.teaching_session_id !== input.teachingSessionId ||
    attempt.attempt_id !== input.attemptId
  ) {
    throw new Error("Tutor Artifact Attempt API returned an invalid payload");
  }
  return attempt;
}

export async function actOnTutorArtifact(input: {
  userId: string;
  conversationId: string;
  artifactId: string;
  learningTrackId: string;
  teachingSessionId: string;
  expectedArtifactVersion: number;
  action: TutorArtifactAction;
  clientActionId: string;
  signal?: AbortSignal;
}): Promise<TutorArtifactActionResponse> {
  const payload = await requestJson(
    `${API_BASE_URL}/api/tutor/conversations/${encodeURIComponent(input.conversationId)}/artifacts/${encodeURIComponent(input.artifactId)}/actions`,
    {
      method: "POST",
      headers: tutorMutationHeaders(input.clientActionId),
      body: JSON.stringify({
        user_id: input.userId,
        learning_track_id: input.learningTrackId,
        teaching_session_id: input.teachingSessionId,
        client_action_id: input.clientActionId,
        expected_artifact_version: input.expectedArtifactVersion,
        action: input.action,
      }),
      signal: input.signal,
    },
  );
  const response = toTutorArtifactActionResponse(payload);
  if (
    !response ||
    response.artifact.id !== input.artifactId ||
    response.artifact.conversation_id !== input.conversationId ||
    response.artifact.learning_track_id !== input.learningTrackId ||
    response.artifact.teaching_session_id !== input.teachingSessionId ||
    response.artifact.version <= input.expectedArtifactVersion
  ) {
    throw new Error("Tutor Artifact action API returned an invalid payload");
  }
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


export async function fetchTeachingSessions(
  userId: string,
  trackId: string,
  signal?: AbortSignal,
): Promise<TeachingSessionListResponse> {
  const query = new URLSearchParams({ user_id: userId });
  const payload = await requestJson(`${API_BASE_URL}/api/learning-tracks/${encodeURIComponent(trackId)}/teaching-sessions?${query.toString()}`, { signal });
  const parsed = toTeachingSessionListResponse(payload);
  if (!parsed) throw new Error("Teaching session list API returned an invalid payload");
  return parsed;
}

export async function openTeachingSession(input: {
  userId: string;
  trackId: string;
  knowledgeKey: string;
  conversationId: string;
  expectedTrackVersion: number;
  expectedProgressVersion: number;
  expectedAssignmentVersion: number;
  mode: TeachingSessionMode;
  clientActionId: string;
  signal?: AbortSignal;
}): Promise<TeachingSessionOpenResponse> {
  const payload = await requestJson(`${API_BASE_URL}/api/learning-tracks/${encodeURIComponent(input.trackId)}/teaching-sessions/${encodeURIComponent(input.knowledgeKey)}/open`, {
    method: "POST",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({
      user_id: input.userId,
      conversation_id: input.conversationId,
      expected_track_version: input.expectedTrackVersion,
      expected_progress_version: input.expectedProgressVersion,
      expected_assignment_version: input.expectedAssignmentVersion,
      mode: input.mode,
      client_action_id: input.clientActionId,
    }),
    signal: input.signal,
  });
  const parsed = toTeachingSessionOpenResponse(payload);
  if (!parsed) throw new Error("Teaching session open API returned an invalid payload");
  return parsed;
}

export async function mutateTeachingSession(input: {
  userId: string;
  trackId: string;
  sessionId: string;
  controlKey: TeachingControlKey;
  expectedSessionVersion: number;
  expectedTrackVersion: number;
  expectedProgressVersion: number;
  expectedAssignmentVersion: number;
  targetMode?: TeachingSessionMode;
  targetKnowledgeKey?: string;
  reasonCode?: string;
  clientActionId: string;
  signal?: AbortSignal;
}): Promise<TeachingSessionActionResponse> {
  const payload = await requestJson(`${API_BASE_URL}/api/learning-tracks/${encodeURIComponent(input.trackId)}/teaching-sessions/${encodeURIComponent(input.sessionId)}/actions`, {
    method: "POST",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({
      user_id: input.userId,
      control_key: input.controlKey,
      expected_session_version: input.expectedSessionVersion,
      expected_track_version: input.expectedTrackVersion,
      expected_progress_version: input.expectedProgressVersion,
      expected_assignment_version: input.expectedAssignmentVersion,
      ...(input.targetMode ? { target_mode: input.targetMode } : {}),
      ...(input.targetKnowledgeKey ? { target_knowledge_key: input.targetKnowledgeKey } : {}),
      ...(input.reasonCode ? { reason_code: input.reasonCode } : {}),
      admit_run: false,
      client_action_id: input.clientActionId,
    }),
    signal: input.signal,
  });
  const parsed = toTeachingSessionActionResponse(payload);
  if (!parsed) throw new Error("Teaching session action API returned an invalid payload");
  return parsed;
}


export function buildTutorConversationEventsUrl(conversationId: string, userId: string): string {
  const url = new URL(`/api/tutor/conversations/${encodeURIComponent(conversationId)}/events`, API_BASE_URL);
  url.searchParams.set("user_id", userId);
  return url.toString();
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
  if (payload.kind === "teaching_session_message") {
    if (
      !hasExactKeys(payload, [...baseKeys, "teaching_session_id", "message_id", "turn_id", "role", "message_summary", "message_created_at"]) ||
      !isString(payload.teaching_session_id) || !isString(payload.message_id) || !isString(payload.turn_id) ||
      (payload.role !== "learner" && payload.role !== "tutor") || !isBoundedString(payload.message_summary, 160) ||
      !isNullableString(payload.message_created_at)
    ) return null;
    return { ...base, kind: "teaching_session_message", teaching_session_id: payload.teaching_session_id,
      message_id: payload.message_id, turn_id: payload.turn_id, role: payload.role,
      message_summary: payload.message_summary, message_created_at: payload.message_created_at };
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

function toTeachingSessionListResponse(payload: unknown): TeachingSessionListResponse | null {
  if (!isRecord(payload) || !hasExactKeys(payload, ["items"]) || !Array.isArray(payload.items) || payload.items.length > 50) return null;
  const items = payload.items.map((item) => toTeachingSessionProjection(item, false));
  if (items.some((item) => item === null)) return null;
  return { items: items.filter((item): item is TeachingSessionProjection => item !== null) };
}

function toTeachingSessionOpenResponse(payload: unknown): TeachingSessionOpenResponse | null {
  if (!isRecord(payload) || !hasExactKeys(payload, ["teaching_session", "created", "pending_run", "idempotent_replayed"]) || typeof payload.created !== "boolean" || typeof payload.idempotent_replayed !== "boolean") return null;
  const session = toTeachingSessionProjection(payload.teaching_session, true);
  if (!session || !isNullableRecord(payload.pending_run)) return null;
  return { teaching_session: session, created: payload.created, pending_run: payload.pending_run, idempotent_replayed: payload.idempotent_replayed };
}

function toTeachingSessionActionResponse(payload: unknown): TeachingSessionActionResponse | null {
  if (!isRecord(payload)) return null;
  const transition = "next_teaching_session" in payload;
  const expected = transition
    ? ["teaching_session", "next_teaching_session", "transitioned", "created", "pending_run", "idempotent_replayed"]
    : ["teaching_session", "pending_run", "idempotent_replayed"];
  if (!hasExactKeys(payload, expected) || !isNullableRecord(payload.pending_run) || typeof payload.idempotent_replayed !== "boolean") return null;
  const session = toTeachingSessionProjection(payload.teaching_session, true);
  if (!session) return null;
  if (!transition) return { teaching_session: session, pending_run: payload.pending_run, idempotent_replayed: payload.idempotent_replayed };
  const next = toTeachingSessionProjection(payload.next_teaching_session, true);
  if (!next || payload.transitioned !== true || typeof payload.created !== "boolean") return null;
  return { teaching_session: session, next_teaching_session: next, transitioned: true, created: payload.created, pending_run: payload.pending_run, idempotent_replayed: payload.idempotent_replayed };
}

function toTeachingSessionProjection(payload: unknown, requireDetails: boolean): TeachingSessionProjection | null {
  const baseKeys = [
    "session_id", "track_id", "track_version", "conversation_id", "knowledge_key", "status", "mode",
    "session_version", "progress_version", "assignment_id", "assignment_version", "document_id", "checkpoint_id",
    "paused_at", "completed_at", "last_activity_at", "action_shelf", "allowed_actions",
  ];
  const detailedKeys = [...baseKeys, "checkpoint"];
  if (!isRecord(payload) || !hasExactKeys(payload, requireDetails ? detailedKeys : baseKeys)) return null;
  if (!isString(payload.session_id) || !isString(payload.track_id) || !isPositiveSafeInteger(payload.track_version) ||
      !isString(payload.conversation_id) || !isStableIdentifier(payload.knowledge_key) || !isTeachingSessionStatus(payload.status) ||
      !isTeachingSessionMode(payload.mode) || !isPositiveSafeInteger(payload.session_version) ||
      !isPositiveSafeInteger(payload.progress_version) || !isString(payload.assignment_id) ||
      !isPositiveSafeInteger(payload.assignment_version) || !isString(payload.document_id) || !isNullableString(payload.checkpoint_id) ||
      !isNullableString(payload.paused_at) || !isNullableString(payload.completed_at) || !isNullableString(payload.last_activity_at)) return null;
  const base: TeachingSessionProjection = {
    session_id: payload.session_id,
    track_id: payload.track_id,
    track_version: payload.track_version,
    conversation_id: payload.conversation_id,
    knowledge_key: payload.knowledge_key,
    status: payload.status,
    mode: payload.mode,
    session_version: payload.session_version,
    progress_version: payload.progress_version,
    assignment_id: payload.assignment_id,
    assignment_version: payload.assignment_version,
    document_id: payload.document_id,
    checkpoint_id: payload.checkpoint_id,
    paused_at: payload.paused_at,
    completed_at: payload.completed_at,
    last_activity_at: payload.last_activity_at,
  };
  if (!isStringArray(payload.allowed_actions) || payload.allowed_actions.length > 12) return null;
  const shelf = payload.action_shelf === null ? null : toTeachingActionShelf(payload.action_shelf);
  if ((payload.action_shelf !== null && shelf === null) || (!requireDetails && (shelf !== null || payload.allowed_actions.length > 0))) return null;
  if (!requireDetails) return { ...base, action_shelf: null, allowed_actions: [] };
  const checkpoint = payload.checkpoint === null ? null : toTeachingCheckpointProjection(payload.checkpoint);
  if (!checkpoint || !shelf) return null;
  const shelfKeys = [shelf.primary_action, ...shelf.secondary_actions, ...shelf.overflow_actions].filter((item): item is TeachingActionDescriptor => item !== null).map((item) => item.key);
  if (payload.allowed_actions.length !== shelfKeys.length || payload.allowed_actions.some((key, index) => key !== shelfKeys[index])) return null;
  return { ...base, checkpoint, action_shelf: shelf, allowed_actions: payload.allowed_actions };
}

function toTeachingSessionGroupProjection(payload: unknown): TeachingSessionGroupProjection | null {
  if (!isRecord(payload) || !("turn_ids" in payload)) return null;
  const { turn_ids: turnIds, ...sessionPayload } = payload;
  const session = toTeachingSessionProjection(sessionPayload, false);
  if (!session || !isStringArray(turnIds) || turnIds.length > 200 || new Set(turnIds).size !== turnIds.length) return null;
  return { ...session, turn_ids: turnIds };
}

function toTeachingCheckpointProjection(payload: unknown): TeachingCheckpointProjection | null {
  const keys = ["checkpoint_id", "session_version", "objective", "active_focus", "suspended_focuses", "unresolved_questions", "covered_concepts", "evidence_cursors", "pause_reason", "recommended_action_key"];
  if (!isRecord(payload) || !hasExactKeys(payload, keys) || !isString(payload.checkpoint_id) || !isPositiveSafeInteger(payload.session_version) ||
      !isRecord(payload.objective) || !hasExactKeys(payload.objective, ["objective_id", "summary", "source_handles"]) ||
      !isStableIdentifier(payload.objective.objective_id) || !isBoundedString(payload.objective.summary, 240) ||
      !isStableStringArray(payload.objective.source_handles, 8) || !Array.isArray(payload.suspended_focuses) || payload.suspended_focuses.length > 8 ||
      !Array.isArray(payload.unresolved_questions) || payload.unresolved_questions.length > 12 ||
      !isStableStringArray(payload.covered_concepts, 32) || !Array.isArray(payload.evidence_cursors) || payload.evidence_cursors.length > 16 ||
      !isTeachingPauseReason(payload.pause_reason) || !isNullableStableIdentifier(payload.recommended_action_key)) return null;
  const activeFocus = payload.active_focus === null ? null : toTeachingFocusProjection(payload.active_focus);
  const suspended = payload.suspended_focuses.map(toTeachingFocusProjection);
  const questions = payload.unresolved_questions.map(toTeachingQuestionProjection);
  const evidence = payload.evidence_cursors.map(toTeachingEvidenceCursor);
  if ((payload.active_focus !== null && activeFocus === null) || suspended.some((item) => item === null) || questions.some((item) => item === null) || evidence.some((item) => item === null)) return null;
  return {
    checkpoint_id: payload.checkpoint_id,
    session_version: payload.session_version,
    objective: { objective_id: payload.objective.objective_id, summary: payload.objective.summary, source_handles: payload.objective.source_handles },
    active_focus: activeFocus,
    suspended_focuses: suspended.filter((item): item is TeachingFocusProjection => item !== null),
    unresolved_questions: questions.filter((item): item is TeachingCheckpointProjection["unresolved_questions"][number] => item !== null),
    covered_concepts: payload.covered_concepts,
    evidence_cursors: evidence.filter((item): item is TeachingCheckpointProjection["evidence_cursors"][number] => item !== null),
    pause_reason: payload.pause_reason,
    recommended_action_key: payload.recommended_action_key,
  };
}

function toTeachingFocusProjection(payload: unknown): TeachingFocusProjection | null {
  if (!isRecord(payload) || !hasExactKeys(payload, ["focus_id", "focus_kind", "summary", "source_handles"]) ||
      !isStableIdentifier(payload.focus_id) || !isTeachingFocusKind(payload.focus_kind) || !isBoundedString(payload.summary, 240) ||
      !isStableStringArray(payload.source_handles, 8)) return null;
  return { focus_id: payload.focus_id, focus_kind: payload.focus_kind, summary: payload.summary, source_handles: payload.source_handles };
}

function toTeachingQuestionProjection(payload: unknown): TeachingCheckpointProjection["unresolved_questions"][number] | null {
  if (!isRecord(payload) || !hasExactKeys(payload, ["question_id", "summary", "state", "source_message_id"]) ||
      !isStableIdentifier(payload.question_id) || !isBoundedString(payload.summary, 180) ||
      (payload.state !== "open" && payload.state !== "answered" && payload.state !== "deferred") || !isNullableString(payload.source_message_id)) return null;
  return { question_id: payload.question_id, summary: payload.summary, state: payload.state, source_message_id: payload.source_message_id };
}

function toTeachingEvidenceCursor(payload: unknown): TeachingCheckpointProjection["evidence_cursors"][number] | null {
  if (!isRecord(payload) || !hasExactKeys(payload, ["evidence_kind", "source_id", "source_version"]) ||
      (payload.evidence_kind !== "gate" && payload.evidence_kind !== "review" && payload.evidence_kind !== "progress" && payload.evidence_kind !== "assignment") ||
      !isString(payload.source_id) || !isPositiveSafeInteger(payload.source_version)) return null;
  return { evidence_kind: payload.evidence_kind, source_id: payload.source_id, source_version: payload.source_version };
}

function toTeachingActionShelf(payload: unknown): TeachingActionShelf | null {
  if (!isRecord(payload) || !hasExactKeys(payload, ["schema_version", "teaching_session_id", "session_version", "checkpoint_id", "state", "primary_action", "secondary_actions", "overflow_actions"]) ||
      payload.schema_version !== "teaching_action_shelf_v1" || !isString(payload.teaching_session_id) || !isPositiveSafeInteger(payload.session_version) ||
      !isString(payload.checkpoint_id) || !isTeachingShelfState(payload.state) || !Array.isArray(payload.secondary_actions) || payload.secondary_actions.length > 3 ||
      !Array.isArray(payload.overflow_actions) || payload.overflow_actions.length > 8) return null;
  const primary = payload.primary_action === null ? null : toTeachingActionDescriptor(payload.primary_action);
  const secondary = payload.secondary_actions.map(toTeachingActionDescriptor);
  const overflow = payload.overflow_actions.map(toTeachingActionDescriptor);
  if ((payload.primary_action !== null && primary === null) || secondary.some((item) => item === null) || overflow.some((item) => item === null)) return null;
  const actions = [primary, ...secondary, ...overflow].filter((item): item is TeachingActionDescriptor => item !== null);
  if ((primary && primary.emphasis !== "primary") || new Set(actions.map((item) => item.key)).size !== actions.length ||
      (["runtime_active", "blocking_request"].includes(payload.state) && actions.length > 0)) return null;
  return { schema_version: "teaching_action_shelf_v1", teaching_session_id: payload.teaching_session_id, session_version: payload.session_version,
    checkpoint_id: payload.checkpoint_id, state: payload.state, primary_action: primary,
    secondary_actions: secondary.filter((item): item is TeachingActionDescriptor => item !== null),
    overflow_actions: overflow.filter((item): item is TeachingActionDescriptor => item !== null) };
}

function toTeachingActionDescriptor(payload: unknown): TeachingActionDescriptor | null {
  if (!isRecord(payload) || !hasExactKeys(payload, ["key", "label", "emphasis", "enabled", "disabled_reason", "target_kind", "target_id", "expected_versions"]) ||
      !isStableIdentifier(payload.key) || !isBoundedString(payload.label, 80) ||
      (payload.emphasis !== "primary" && payload.emphasis !== "secondary" && payload.emphasis !== "quiet") || typeof payload.enabled !== "boolean" ||
      !isNullableBoundedString(payload.disabled_reason, 160) || (payload.target_kind !== "teaching_control" && payload.target_kind !== "navigation" && payload.target_kind !== "artifact") ||
      !isNullableString(payload.target_id) || !isRecord(payload.expected_versions)) return null;
  const versionKeys = Object.keys(payload.expected_versions);
  if (versionKeys.some((key) => !["session", "track", "progress", "assignment"].includes(key)) ||
      Object.values(payload.expected_versions).some((value) => !isPositiveSafeInteger(value))) return null;
  return { key: payload.key, label: payload.label, emphasis: payload.emphasis, enabled: payload.enabled,
    disabled_reason: payload.disabled_reason, target_kind: payload.target_kind, target_id: payload.target_id,
    expected_versions: payload.expected_versions as TeachingActionDescriptor["expected_versions"] };
}

function isTeachingSessionMode(value: unknown): value is TeachingSessionMode { return value === "guided" || value === "free_reading"; }
function isTeachingSessionStatus(value: unknown): value is TeachingSessionProjection["status"] { return value === "active" || value === "paused" || value === "completed" || value === "blocked"; }
function isTeachingPauseReason(value: unknown): value is TeachingCheckpointProjection["pause_reason"] { return value === "soft_pause" || value === "evidence_pause" || value === "authority_pause" || value === "session_pause" || value === "completion_pause"; }
function isTeachingFocusKind(value: unknown): value is TeachingFocusProjection["focus_kind"] { return value === "knowledge" || value === "lesson_block" || value === "question" || value === "prerequisite" || value === "feedback"; }
function isTeachingShelfState(value: unknown): value is TeachingActionShelf["state"] { return value === "ready" || value === "runtime_active" || value === "blocking_request" || value === "completion" || value === "free_reading"; }
function isStableIdentifier(value: unknown): value is string { return typeof value === "string" && /^[a-z0-9][a-z0-9._:-]{0,159}$/.test(value); }
function isNullableStableIdentifier(value: unknown): value is string | null { return value === null || isStableIdentifier(value); }
function isBoundedString(value: unknown, maximum: number): value is string { return typeof value === "string" && value.length > 0 && value.length <= maximum; }
function isNullableBoundedString(value: unknown, maximum: number): value is string | null { return value === null || isBoundedString(value, maximum); }
function isStableStringArray(value: unknown, maximum: number): value is string[] { return Array.isArray(value) && value.length <= maximum && value.every(isStableIdentifier) && new Set(value).size === value.length; }
function isNullableRecord(value: unknown): value is Record<string, unknown> | null { return value === null || isRecord(value); }


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
  if (hasProtectedArtifactMarker(payload)) return null;
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
  if (payload.kind === "artifact") {
    return toTutorPublicArtifactItem(payload);
  }
  return null;
}

const ARTIFACT_PROTECTED_MARKERS = [
  "__AEARN_PRIVATE_SUBMISSION__",
  "__AEARN_HIDDEN_TEST__",
  "__AEARN_PRIVATE_RUBRIC__",
  "__AEARN_REFERENCE_ANSWER__",
  "__AEARN_PROVIDER_BODY__",
  "__AEARN_PROVIDER_REASONING__",
  "__AEARN_PRIVATE_COMMAND_PATH__",
  "__AEARN_CONTAINER_SECRET__",
] as const;

const ARTIFACT_PROTECTED_KEYS = new Set([
  "submission", "submitted_code", "content_text", "private_rubric", "private_rubric_json",
  "private_test_bundle", "private_test_bundle_json", "hidden_test", "hidden_tests", "hidden_test_ids",
  "reference_answer", "reference_answer_json", "solution_reference", "provider_body", "provider_payload",
  "provider_response", "provider_reasoning", "reasoning", "reasoning_content", "raw_reasoning", "prompt",
  "raw_prompt", "raw_result", "raw_payload", "rubric", "command", "command_line", "path", "file_path",
  "filesystem_path", "working_directory", "mount", "mounts", "container", "container_id", "container_name",
  "image", "image_id", "image_digest", "secret", "credential", "api_key",
]);

const SAFE_EXECUTION_PROTECTED_LINE = /(?:docker|container|image[_ -]?(?:id|digest|reference)|sha256:|error response from daemon|hidden(?:[_ -]?test|[_ -]?case)|private(?:[_ -]?(?:test|rubric|payload))|solution[_ -]?(?:reference|answer)|reference[_ -]?answer|expected(?:[_ -]?(?:value|input|output))?|traceback|stack trace|^\s*at\s+[a-z0-9_.$<>]+|^\s*caused by:|\bfile "|[a-z]:[\\/]|\/(?:tmp|var|workspace|work|app|home|opt|etc|usr)(?:\/|\b)|```|\b(?:def|class|function)\s+[a-z_]|^\s*(?:return|raise|import|from)\b|\b(?:command|cmd(?:\.exe)?|powershell|pwsh|bash|sh\s+-c|subprocess)\b|(?:api[_ -]?key|authorization|bearer|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|password|passwd|credential|database[_ -]?url|redis[_ -]?url)\s*[:=]|\bbearer\s+[a-z0-9._~+/=-]{8,}|\bsk-[a-z0-9_-]{8,}|-----begin [a-z ]*private key-----|\bAKIA[0-9A-Z]{16}\b|\b[a-z0-9][a-z0-9.-]*\.[a-z0-9.-]+(?:\/[a-z0-9._-]+)+(?:@sha256:[0-9a-f]{64}|:[a-z0-9._-]+))/i;

function toTutorPublicArtifactItem(payload: unknown): TutorPublicArtifactItem | null {
  if (!isRecord(payload) || hasProtectedArtifactData(payload) || !hasExactKeys(payload, [
    "kind", "id", "conversation_id", "turn_id", "learning_track_id", "knowledge_key",
    "teaching_session_id", "checkpoint_id", "artifact_version", "artifact_kind", "purpose", "owner_kind",
    "owner_id", "owner_version", "state", "blocking", "title", "instruction_markdown", "difficulty",
    "presentation", "allowed_actions", "source_references", "active_attempt", "branch_summary", "version",
    "created_at", "updated_at", "terminal_at",
  ]) || payload.kind !== "artifact" || !isArtifactBoundedString(payload.id, 160) ||
      !isArtifactBoundedString(payload.conversation_id, 160) || !isNullableArtifactBoundedString(payload.turn_id, 160) ||
      !isArtifactBoundedString(payload.learning_track_id, 160) || !isArtifactStableKey(payload.knowledge_key) ||
      !isArtifactBoundedString(payload.teaching_session_id, 160) || !isArtifactBoundedString(payload.checkpoint_id, 160) ||
      payload.artifact_version !== 1 || !isTutorArtifactKind(payload.artifact_kind) ||
      !isTutorArtifactPurpose(payload.purpose) || !isTutorArtifactOwnerKind(payload.owner_kind) ||
      !isArtifactBoundedString(payload.owner_id, 160) || !isPositiveSafeInteger(payload.owner_version) ||
      !isTutorArtifactState(payload.state) || typeof payload.blocking !== "boolean" ||
      !isArtifactBoundedString(payload.title, 240) || !isArtifactBoundedString(payload.instruction_markdown, 8_000) ||
      !(payload.difficulty === null || isTutorArtifactDifficulty(payload.difficulty)) ||
      !isPositiveSafeInteger(payload.version) || !isArtifactBoundedString(payload.created_at, 80) ||
      !isArtifactBoundedString(payload.updated_at, 80) || !isNullableArtifactBoundedString(payload.terminal_at, 80)) return null;

  const presentation = toTutorArtifactPresentation(payload.presentation);
  const allowedActions = toTutorArtifactActionKinds(payload.allowed_actions);
  const sourceReferences = toTutorArtifactSourceReferences(payload.source_references);
  const activeAttempt = payload.active_attempt === null ? null : toTutorArtifactAttemptSummary(payload.active_attempt);
  const branchSummary = payload.branch_summary === null ? null : toTutorArtifactBranchSummary(payload.branch_summary);
  if (!presentation || !allowedActions || !sourceReferences ||
      (payload.active_attempt !== null && activeAttempt === null) ||
      (payload.branch_summary !== null && branchSummary === null) ||
      !doesTutorArtifactKindMatchPresentation(payload.artifact_kind, presentation.type)) return null;

  const terminal = isTutorArtifactTerminalState(payload.state);
  if (terminal !== (payload.terminal_at !== null) || (terminal && allowedActions.length > 0) ||
      (terminal && activeAttempt !== null && activeAttempt.status !== "terminal")) return null;
  if (presentation.type === "model_code_review_v2" && (
      ((payload.state === "completed") !== presentation.submission_locked) ||
      (!terminal && !allowedActions.includes("complete_review"))
    )) return null;
  if (payload.artifact_kind === "test_result") {
    if (payload.purpose !== "result" || payload.state !== "completed" || payload.blocking ||
        allowedActions.length > 0 || activeAttempt === null || activeAttempt.status !== "terminal" ||
        presentation.type !== "test_result_v1" || presentation.status !== "terminal" ||
        presentation.attempt_id !== activeAttempt.attempt_id || presentation.outcome !== activeAttempt.outcome ||
        presentation.result_hash !== activeAttempt.result_hash) return null;
    const sourceRefs = sourceReferences.filter((reference) => reference.kind === "artifact");
    const attemptRefs = sourceReferences.filter((reference) => reference.kind === "attempt_result");
    if (sourceRefs.length !== 1 || sourceRefs[0].reference_version === null || attemptRefs.length !== 1 ||
        attemptRefs[0].reference_id !== activeAttempt.attempt_id ||
        attemptRefs[0].content_hash !== activeAttempt.result_hash) return null;
  }

  return {
    kind: "artifact",
    id: payload.id,
    conversation_id: payload.conversation_id,
    turn_id: payload.turn_id,
    learning_track_id: payload.learning_track_id,
    knowledge_key: payload.knowledge_key,
    teaching_session_id: payload.teaching_session_id,
    checkpoint_id: payload.checkpoint_id,
    artifact_version: 1,
    artifact_kind: payload.artifact_kind,
    purpose: payload.purpose,
    owner_kind: payload.owner_kind,
    owner_id: payload.owner_id,
    owner_version: payload.owner_version,
    state: payload.state,
    blocking: payload.blocking,
    title: payload.title,
    instruction_markdown: payload.instruction_markdown,
    difficulty: payload.difficulty,
    presentation,
    allowed_actions: allowedActions,
    source_references: sourceReferences,
    active_attempt: activeAttempt,
    branch_summary: branchSummary,
    version: payload.version,
    created_at: payload.created_at,
    updated_at: payload.updated_at,
    terminal_at: payload.terminal_at,
  };
}

function toTutorArtifactPresentation(payload: unknown): TutorArtifactPresentation | null {
  if (!isRecord(payload) || !isString(payload.type)) return null;
  if (payload.type === "exercise_workspace_v1" && hasExactKeys(payload, [
    "type", "exercise_version_id", "language_id", "editor_mode", "starter_content", "starter_content_hash",
    "editable", "live_preview", "runtime_profile_key",
  ]) && isArtifactBoundedString(payload.exercise_version_id, 160) && isArtifactStableKey(payload.language_id) &&
      (payload.editor_mode === "code" || payload.editor_mode === "sql" || payload.editor_mode === "structured_answer") &&
      isArtifactString(payload.starter_content, 48_000) && isSha256(payload.starter_content_hash) &&
      sha256Text(payload.starter_content) === payload.starter_content_hash && typeof payload.editable === "boolean" &&
      typeof payload.live_preview === "boolean" && isNullableArtifactStableKey(payload.runtime_profile_key)) {
    return {
      type: "exercise_workspace_v1", exercise_version_id: payload.exercise_version_id, language_id: payload.language_id,
      editor_mode: payload.editor_mode, starter_content: payload.starter_content,
      starter_content_hash: payload.starter_content_hash, editable: payload.editable, live_preview: payload.live_preview,
      runtime_profile_key: payload.runtime_profile_key,
    };
  }
  if (payload.type === "browser_preview_v1" && hasExactKeys(payload, [
    "type", "source_artifact_id", "source_content_hash", "experience_tier", "interactive",
  ]) && isArtifactBoundedString(payload.source_artifact_id, 160) && isSha256(payload.source_content_hash) &&
      payload.experience_tier === "local_non_authoritative" && typeof payload.interactive === "boolean") {
    return { type: "browser_preview_v1", source_artifact_id: payload.source_artifact_id,
      source_content_hash: payload.source_content_hash, experience_tier: "local_non_authoritative", interactive: payload.interactive };
  }
  if (payload.type === "test_result_v1" && hasExactKeys(payload, [
    "type", "attempt_id", "status", "outcome", "passed_count", "total_count", "summary_markdown", "result_hash",
  ]) && isArtifactBoundedString(payload.attempt_id, 160) && (payload.status === "pending" || payload.status === "terminal") &&
      isNullableTutorArtifactOutcome(payload.outcome) && isArtifactIntegerInRange(payload.passed_count, 0, 10_000) &&
      isArtifactIntegerInRange(payload.total_count, 0, 10_000) && payload.passed_count <= payload.total_count &&
      isArtifactString(payload.summary_markdown, 4_000) && isNullableSha256(payload.result_hash) &&
      ((payload.status === "terminal") === (payload.outcome !== null && payload.result_hash !== null))) {
    return { type: "test_result_v1", attempt_id: payload.attempt_id, status: payload.status, outcome: payload.outcome,
      passed_count: payload.passed_count, total_count: payload.total_count, summary_markdown: payload.summary_markdown,
      result_hash: payload.result_hash };
  }
  if (payload.type === "knowledge_check_v1" && hasRequiredAndOptionalKeys(payload, [
    "type", "response_kind", "prompt_markdown", "options", "minimum_selections", "maximum_selections", "maximum_text_length",
  ], [
    "hints", "revealed_hint_levels", "answer_locked", "outcome", "assistance_kind", "evaluation_markdown",
    "response_receipt_id", "remediation_handle", "transfer_handle",
  ]) && isTutorArtifactResponseKind(payload.response_kind) && isArtifactBoundedString(payload.prompt_markdown, 8_000) &&
      isArtifactIntegerInRange(payload.minimum_selections, 1, 24) && isArtifactIntegerInRange(payload.maximum_selections, 1, 24) &&
      isArtifactIntegerInRange(payload.maximum_text_length, 1, 8_000)) {
    const options = toTutorArtifactOptions(payload.options);
    const selectKind = payload.response_kind === "single_select" || payload.response_kind === "multi_select" || payload.response_kind === "ordering";
    if (!options || selectKind !== (options.length > 0) || payload.maximum_selections < payload.minimum_selections ||
        (payload.response_kind === "single_select" && payload.maximum_selections !== 1) ||
        (payload.response_kind === "ordering" && (payload.minimum_selections !== options.length || payload.maximum_selections !== options.length)) ||
        (options.length > 0 && payload.maximum_selections > options.length)) return null;
    const hints = payload.hints === undefined ? [] : toKnowledgeCheckHints(payload.hints);
    const revealedHintLevels = payload.revealed_hint_levels === undefined ? [] : toHintLevels(payload.revealed_hint_levels);
    if (!hints || !revealedHintLevels || revealedHintLevels.length > hints.length ||
        payload.answer_locked !== undefined && typeof payload.answer_locked !== "boolean" ||
        payload.outcome !== undefined && payload.outcome !== null && payload.outcome !== "correct" && payload.outcome !== "incorrect" ||
        payload.assistance_kind !== undefined && !isKnowledgeCheckAssistanceKind(payload.assistance_kind) ||
        payload.evaluation_markdown !== undefined && !isArtifactString(payload.evaluation_markdown, 4_000) ||
        payload.response_receipt_id !== undefined && !isNullableArtifactBoundedString(payload.response_receipt_id, 160) ||
        payload.remediation_handle !== undefined && !isNullableLearningItemHandle(payload.remediation_handle) ||
        payload.transfer_handle !== undefined && !isNullableLearningItemHandle(payload.transfer_handle)) return null;
    const answerLocked = payload.answer_locked ?? false;
    const outcome = payload.outcome ?? null;
    const assistanceKind = payload.assistance_kind === undefined ? null : payload.assistance_kind;
    const evaluationMarkdown = payload.evaluation_markdown ?? "";
    const responseReceiptId = payload.response_receipt_id ?? null;
    if (answerLocked !== (outcome !== null && assistanceKind !== null && evaluationMarkdown.length > 0 && responseReceiptId !== null)) return null;
    return { type: "knowledge_check_v1", response_kind: payload.response_kind, prompt_markdown: payload.prompt_markdown,
      options, minimum_selections: payload.minimum_selections, maximum_selections: payload.maximum_selections,
      maximum_text_length: payload.maximum_text_length, hints, revealed_hint_levels: revealedHintLevels,
      answer_locked: answerLocked, outcome, assistance_kind: assistanceKind, evaluation_markdown: evaluationMarkdown,
      response_receipt_id: responseReceiptId, remediation_handle: payload.remediation_handle ?? null,
      transfer_handle: payload.transfer_handle ?? null };
  }
  if (payload.type === "model_code_review_v1" && hasExactKeys(payload, [
    "type", "exercise_version_id", "language_id", "source_code", "source_code_hash", "line_count", "review_categories",
  ]) && isArtifactBoundedString(payload.exercise_version_id, 160) && isArtifactStableKey(payload.language_id) &&
      isArtifactBoundedString(payload.source_code, 48_000) && isSha256(payload.source_code_hash) &&
      isArtifactIntegerInRange(payload.line_count, 1, 4_000)) {
    const normalizedSource = normalizeArtifactNewlines(payload.source_code);
    const categories = toArtifactStableKeyArray(payload.review_categories, 16);
    if (!categories || sha256Text(normalizedSource) !== payload.source_code_hash ||
        pythonSplitlinesCount(normalizedSource) !== payload.line_count) return null;
    return { type: "model_code_review_v1", exercise_version_id: payload.exercise_version_id,
      language_id: payload.language_id, source_code: payload.source_code, source_code_hash: payload.source_code_hash,
      line_count: payload.line_count, review_categories: categories };
  }
  if (payload.type === "model_code_review_v2" && hasExactKeys(payload, [
    "type", "exercise_version_id", "presentation_hash", "review_target", "review_categories",
    "submission_locked", "outcome", "score", "evaluation_markdown", "review_receipt_id", "result_hash",
    "remediation_handle",
  ]) && isArtifactBoundedString(payload.exercise_version_id, 160) && isSha256(payload.presentation_hash) &&
      typeof payload.submission_locked === "boolean" &&
      (payload.outcome === null || payload.outcome === "passed" || payload.outcome === "failed") &&
      (payload.score === null || isArtifactScore(payload.score)) && isArtifactString(payload.evaluation_markdown, 4_000) &&
      isNullableArtifactBoundedString(payload.review_receipt_id, 160) && isNullableSha256(payload.result_hash) &&
      isNullableLearningItemHandle(payload.remediation_handle)) {
    const reviewTarget = toModelReviewArtifactV2(payload.review_target);
    const categories = toModelReviewCategoriesV2(payload.review_categories);
    const terminalFields = payload.outcome !== null && payload.score !== null && payload.evaluation_markdown.length > 0 &&
      payload.review_receipt_id !== null && payload.result_hash !== null;
    if (!reviewTarget || !categories || payload.presentation_hash !== sha256Text(canonicalJson(reviewTarget)) ||
        payload.submission_locked !== terminalFields || (!payload.submission_locked && (
          payload.outcome !== null || payload.score !== null || payload.evaluation_markdown.length > 0 ||
          payload.review_receipt_id !== null || payload.result_hash !== null || payload.remediation_handle !== null
        )) || (payload.submission_locked &&
          ((payload.outcome === "failed") !== (payload.remediation_handle !== null)))) return null;
    return {
      type: "model_code_review_v2", exercise_version_id: payload.exercise_version_id,
      presentation_hash: payload.presentation_hash, review_target: reviewTarget, review_categories: categories,
      submission_locked: payload.submission_locked, outcome: payload.outcome, score: payload.score,
      evaluation_markdown: payload.evaluation_markdown, review_receipt_id: payload.review_receipt_id,
      result_hash: payload.result_hash, remediation_handle: payload.remediation_handle,
    };
  }
  if (payload.type === "sql_workspace_v1" && hasExactKeys(payload, [
    "type", "exercise_version_id", "dialect", "starter_query", "starter_query_hash", "schema_markdown", "max_rows",
  ]) && isArtifactBoundedString(payload.exercise_version_id, 160) && payload.dialect === "sqlite" &&
      isArtifactString(payload.starter_query, 48_000) && isSha256(payload.starter_query_hash) &&
      sha256Text(payload.starter_query) === payload.starter_query_hash &&
      isArtifactBoundedString(payload.schema_markdown, 12_000) && isArtifactIntegerInRange(payload.max_rows, 1, 200)) {
    return { type: "sql_workspace_v1", exercise_version_id: payload.exercise_version_id, dialect: "sqlite",
      starter_query: payload.starter_query, starter_query_hash: payload.starter_query_hash,
      schema_markdown: payload.schema_markdown, max_rows: payload.max_rows };
  }
  if (payload.type === "demonstration_v1" && hasExactKeys(payload, [
    "type", "demonstration_mode", "language_id", "source_content", "source_content_hash", "expected_event_key", "duration_seconds",
  ]) && (payload.demonstration_mode === "interactive" || payload.demonstration_mode === "static") &&
      isNullableArtifactStableKey(payload.language_id) && isArtifactBoundedString(payload.source_content, 48_000) &&
      isSha256(payload.source_content_hash) && sha256Text(payload.source_content) === payload.source_content_hash &&
      isNullableArtifactBoundedString(payload.expected_event_key, 160) &&
      (payload.duration_seconds === null || isArtifactIntegerInRange(payload.duration_seconds, 6, 30))) {
    if ((payload.demonstration_mode === "interactive" && (payload.expected_event_key === null || payload.duration_seconds !== null)) ||
        (payload.demonstration_mode === "static" && (payload.duration_seconds === null || payload.expected_event_key !== null))) return null;
    return { type: "demonstration_v1", demonstration_mode: payload.demonstration_mode, language_id: payload.language_id,
      source_content: payload.source_content, source_content_hash: payload.source_content_hash,
      expected_event_key: payload.expected_event_key, duration_seconds: payload.duration_seconds };
  }
  if (payload.type === "demonstration_v2" && hasExactKeys(payload, [
    "type", "descriptor_version", "demonstration_mode", "source_version", "language_id", "steps",
    "expected_event", "total_duration_seconds", "completion_policy_version",
  ]) && payload.descriptor_version === "demonstration_descriptor_v1" &&
      (payload.demonstration_mode === "interactive" || payload.demonstration_mode === "static") &&
      isArtifactStableKey(payload.source_version) && isArtifactStableKey(payload.language_id) &&
      payload.completion_policy_version === "demonstration_completion_policy_v1" && Array.isArray(payload.steps) &&
      payload.steps.length >= 1 && payload.steps.length <= 8) {
    const steps = payload.steps.map(toTutorDemonstrationStep);
    if (steps.some((step) => step === null)) return null;
    const safeSteps = steps.filter((step): step is NonNullable<typeof step> => step !== null);
    const expected = payload.expected_event === null ? null : toTutorDemonstrationEvent(payload.expected_event);
    if (payload.expected_event !== null && expected === null) return null;
    const total = payload.total_duration_seconds;
    if (total !== null && !isArtifactIntegerInRange(total, 6, 240)) return null;
    const durations = safeSteps.map((step) => step.duration_seconds);
    if (payload.demonstration_mode === "interactive") {
      if (safeSteps.length !== 1 || expected === null || total !== null || durations.some((value) => value !== null)) return null;
    } else if (expected !== null || total === null || durations.some((value) => value === null) ||
        durations.reduce<number>((sum, value) => sum + (value ?? 0), 0) !== total) return null;
    return { type: "demonstration_v2", descriptor_version: "demonstration_descriptor_v1",
      demonstration_mode: payload.demonstration_mode, source_version: payload.source_version, language_id: payload.language_id,
      steps: safeSteps, expected_event: expected, total_duration_seconds: total,
      completion_policy_version: "demonstration_completion_policy_v1" };
  }
  if (payload.type === "source_inspector_v1" && hasExactKeys(payload, [
    "type", "document_id", "document_content_hash", "block_id", "excerpt", "citation_ids",
  ]) && isArtifactBoundedString(payload.document_id, 160) && isSha256(payload.document_content_hash) &&
      isArtifactBoundedString(payload.block_id, 160) && isArtifactBoundedString(payload.excerpt, 800)) {
    const citationIds = toArtifactBoundedStringArray(payload.citation_ids, 12, 160);
    if (!citationIds) return null;
    return { type: "source_inspector_v1", document_id: payload.document_id,
      document_content_hash: payload.document_content_hash, block_id: payload.block_id,
      excerpt: payload.excerpt, citation_ids: citationIds };
  }
  return null;
}

const MODEL_REVIEW_REQUIRED_CATEGORIES = [
  "requirements_drift", "fabricated_api", "logic_boundary", "contract_integration", "async_lifecycle",
  "security_trust", "error_false_success",
] as const;

function toModelReviewCategoriesV2(value: unknown): ModelReviewErrorCategoryV2[] | null {
  if (!Array.isArray(value) || value.length < 7 || value.length > 8 || !value.every(isModelReviewCategoryV2)) return null;
  const categories = value as ModelReviewErrorCategoryV2[];
  return new Set(categories).size === categories.length && MODEL_REVIEW_REQUIRED_CATEGORIES.every((item) => categories.includes(item))
    ? [...categories]
    : null;
}

function isModelReviewCategoryV2(value: unknown): value is ModelReviewErrorCategoryV2 {
  return value === "requirements_drift" || value === "fabricated_api" || value === "logic_boundary" ||
    value === "contract_integration" || value === "async_lifecycle" || value === "security_trust" ||
    value === "error_false_success" || value === "weak_testing";
}

function toModelReviewArtifactV2(value: unknown): ModelReviewArtifactV2 | null {
  if (!isRecord(value) || !hasExactKeys(value, [
    "schema_version", "presentation_mode", "language_id", "runtime_label", "source_code", "modified_code",
    "source_hash", "modified_hash", "diff_hash", "line_count", "hunks",
  ]) || value.schema_version !== "model_code_review_artifact_v2" ||
      (value.presentation_mode !== "code" && value.presentation_mode !== "diff") || !isArtifactStableKey(value.language_id) ||
      !isArtifactBoundedString(value.runtime_label, 120) || !isNullableArtifactString(value.source_code, 48_000) ||
      !isArtifactBoundedString(value.modified_code, 48_000) || !isNullableSha256(value.source_hash) ||
      !isSha256(value.modified_hash) || !isSha256(value.diff_hash) || !isArtifactIntegerInRange(value.line_count, 1, 4_000) ||
      !Array.isArray(value.hunks) || value.hunks.length < 1 || value.hunks.length > 80) return null;
  const source = value.source_code === null ? null : normalizeArtifactNewlines(value.source_code);
  const modified = normalizeArtifactNewlines(value.modified_code);
  if (pythonSplitlinesCount(modified) !== value.line_count || modelReviewCodeHash(modified) !== value.modified_hash ||
      (value.presentation_mode === "code" && (source !== null || value.source_hash !== null)) ||
      (value.presentation_mode === "diff" && (source === null || value.source_hash !== modelReviewCodeHash(source) || source === modified))) return null;
  const hunks = value.hunks.map(toModelReviewDiffHunkV2);
  if (hunks.some((item) => item === null)) return null;
  const safeHunks = hunks.filter((item): item is ModelReviewDiffHunkV2 => item !== null);
  if (new Set(safeHunks.map((item) => item.hunk_id)).size !== safeHunks.length ||
      !isModelReviewLineMapBoundToCode(value.presentation_mode, source, modified, safeHunks)) return null;
  const identity = { presentation_mode: value.presentation_mode, source_hash: value.source_hash, modified_hash: value.modified_hash, hunks: safeHunks };
  if (sha256Text(canonicalJson(identity)) !== value.diff_hash) return null;
  return {
    schema_version: "model_code_review_artifact_v2", presentation_mode: value.presentation_mode,
    language_id: value.language_id, runtime_label: value.runtime_label, source_code: source,
    modified_code: modified, source_hash: value.source_hash, modified_hash: value.modified_hash,
    diff_hash: value.diff_hash, line_count: value.line_count, hunks: safeHunks,
  };
}

function toModelReviewDiffHunkV2(value: unknown): ModelReviewDiffHunkV2 | null {
  if (!isRecord(value) || !hasExactKeys(value, [
    "hunk_id", "header", "source_start", "source_count", "modified_start", "modified_count", "lines",
  ]) || !isArtifactStableKey(value.hunk_id) || !isArtifactBoundedString(value.header, 240) ||
      !isArtifactIntegerInRange(value.source_start, 0, 4_000) || !isArtifactIntegerInRange(value.source_count, 0, 4_000) ||
      !isArtifactIntegerInRange(value.modified_start, 0, 4_000) || !isArtifactIntegerInRange(value.modified_count, 0, 4_000) ||
      !Array.isArray(value.lines) || value.lines.length < 1 || value.lines.length > 800) return null;
  const lines = value.lines.map(toModelReviewDiffLineV2);
  if (lines.some((item) => item === null)) return null;
  const safeLines = lines.filter((item): item is ModelReviewDiffLineV2 => item !== null);
  const sourceLines = safeLines.flatMap((item) => item.source_line === null ? [] : [item.source_line]);
  const modifiedLines = safeLines.flatMap((item) => item.modified_line === null ? [] : [item.modified_line]);
  if (new Set(safeLines.map((item) => item.line_key)).size !== safeLines.length ||
      sourceLines.some((item, index) => index > 0 && item < sourceLines[index - 1]) ||
      modifiedLines.some((item, index) => index > 0 && item < modifiedLines[index - 1])) return null;
  return { hunk_id: value.hunk_id, header: value.header, source_start: value.source_start, source_count: value.source_count,
    modified_start: value.modified_start, modified_count: value.modified_count, lines: safeLines };
}

function toModelReviewDiffLineV2(value: unknown): ModelReviewDiffLineV2 | null {
  if (!isRecord(value) || !hasExactKeys(value, ["line_key", "kind", "text", "source_line", "modified_line"]) ||
      !isArtifactStableKey(value.line_key) || (value.kind !== "context" && value.kind !== "added" && value.kind !== "removed") ||
      !isArtifactString(value.text, 4_000) || !(value.source_line === null || isArtifactIntegerInRange(value.source_line, 1, 4_000)) ||
      !(value.modified_line === null || isArtifactIntegerInRange(value.modified_line, 1, 4_000))) return null;
  if ((value.kind === "added" && (value.source_line !== null || value.modified_line === null)) ||
      (value.kind === "removed" && (value.source_line === null || value.modified_line !== null)) ||
      (value.kind === "context" && (value.source_line === null || value.modified_line === null))) return null;
  return { line_key: value.line_key, kind: value.kind, text: value.text, source_line: value.source_line, modified_line: value.modified_line };
}

function isModelReviewLineMapBoundToCode(
  mode: "code" | "diff",
  source: string | null,
  modified: string,
  hunks: ModelReviewDiffHunkV2[],
): boolean {
  const modifiedLines = pythonSplitlines(modified);
  if (mode === "code") {
    if (source !== null || hunks.length !== 1) return false;
    const hunk = hunks[0];
    if (hunk.hunk_id !== "code.h1" || hunk.header !== `@@ -1,${modifiedLines.length} +1,${modifiedLines.length} @@` ||
        hunk.source_start !== 1 || hunk.source_count !== modifiedLines.length || hunk.modified_start !== 1 ||
        hunk.modified_count !== modifiedLines.length || hunk.lines.length !== modifiedLines.length) return false;
    return hunk.lines.every((line, index) => line.line_key === `code.m${index + 1}` && line.kind === "context" &&
      line.text === modifiedLines[index] && line.source_line === index + 1 && line.modified_line === index + 1);
  }
  if (source === null) return false;
  const sourceLines = pythonSplitlines(source);
  let sourceCursor = 1;
  let modifiedCursor = 1;
  for (const [hunkIndex, hunk] of hunks.entries()) {
    if (hunk.hunk_id !== `diff.h${hunkIndex + 1}` || hunk.source_count < 1 || hunk.modified_count < 1 ||
        hunk.header !== `@@ -${hunk.source_start},${hunk.source_count} +${hunk.modified_start},${hunk.modified_count} @@` ||
        hunk.source_start < sourceCursor || hunk.modified_start < modifiedCursor) return false;
    const unchangedSource = sourceLines.slice(sourceCursor - 1, hunk.source_start - 1);
    const unchangedModified = modifiedLines.slice(modifiedCursor - 1, hunk.modified_start - 1);
    if (!sameStrings(unchangedSource, unchangedModified)) return false;
    const projectedSource: string[] = [];
    const projectedModified: string[] = [];
    let changed = false;
    for (const [lineIndex, line] of hunk.lines.entries()) {
      if (line.line_key !== `h${hunkIndex + 1}.l${lineIndex + 1}`) return false;
      if (line.source_line !== null) {
        if (line.source_line < 1 || line.source_line > sourceLines.length || sourceLines[line.source_line - 1] !== line.text) return false;
        projectedSource.push(line.text);
      }
      if (line.modified_line !== null) {
        if (line.modified_line < 1 || line.modified_line > modifiedLines.length || modifiedLines[line.modified_line - 1] !== line.text) return false;
        projectedModified.push(line.text);
      }
      if (line.kind === "context") {
        if (line.source_line === null || line.modified_line === null ||
            sourceLines[line.source_line - 1] !== modifiedLines[line.modified_line - 1]) return false;
      } else {
        changed = true;
      }
    }
    if (!changed || projectedSource.length !== hunk.source_count || projectedModified.length !== hunk.modified_count ||
        !sameStrings(projectedSource, sourceLines.slice(hunk.source_start - 1, hunk.source_start - 1 + hunk.source_count)) ||
        !sameStrings(projectedModified, modifiedLines.slice(hunk.modified_start - 1, hunk.modified_start - 1 + hunk.modified_count))) return false;
    const sourceNumbers = hunk.lines.flatMap((line) => line.source_line === null ? [] : [line.source_line]);
    const modifiedNumbers = hunk.lines.flatMap((line) => line.modified_line === null ? [] : [line.modified_line]);
    if (!isExactLineRange(sourceNumbers, hunk.source_start, hunk.source_count) ||
        !isExactLineRange(modifiedNumbers, hunk.modified_start, hunk.modified_count)) return false;
    sourceCursor = hunk.source_start + hunk.source_count;
    modifiedCursor = hunk.modified_start + hunk.modified_count;
  }
  return sameStrings(sourceLines.slice(sourceCursor - 1), modifiedLines.slice(modifiedCursor - 1));
}

function isExactLineRange(values: number[], start: number, count: number): boolean {
  return values.length === count && values.every((value, index) => value === start + index);
}

function sameStrings(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function modelReviewCodeHash(value: string): string {
  return sha256Text(canonicalJson({ code: value }));
}

function isNullableArtifactString(value: unknown, maximum: number): value is string | null {
  return value === null || isArtifactString(value, maximum);
}

function toTutorDemonstrationStep(value: unknown) {
  if (!isRecord(value) || !hasExactKeys(value, ["step_key", "title", "instruction_markdown", "source_content", "source_content_hash", "duration_seconds"]) ||
      !isArtifactStableKey(value.step_key) || !isArtifactBoundedString(value.title, 160) ||
      !isArtifactBoundedString(value.instruction_markdown, 2_000) || !isArtifactBoundedString(value.source_content, 12_000) ||
      !isSha256(value.source_content_hash) || sha256Text(value.source_content) !== value.source_content_hash ||
      (value.duration_seconds !== null && !isArtifactIntegerInRange(value.duration_seconds, 6, 30))) return null;
  return { step_key: value.step_key, title: value.title, instruction_markdown: value.instruction_markdown,
    source_content: value.source_content, source_content_hash: value.source_content_hash, duration_seconds: value.duration_seconds };
}

function toTutorDemonstrationEvent(value: unknown) {
  if (!isRecord(value) || !hasExactKeys(value, ["event_key", "payload_json", "payload_hash"]) ||
      !isArtifactStableKey(value.event_key) || !isSafeArtifactDemoPayload(value.payload_json) || !isSha256(value.payload_hash) ||
      sha256Text(canonicalJson(value.payload_json)) !== value.payload_hash) return null;
  return { event_key: value.event_key, payload_json: value.payload_json, payload_hash: value.payload_hash };
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (isRecord(value)) return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
  return JSON.stringify(value);
}

function isSafeArtifactDemoPayload(value: unknown): value is Readonly<Record<string, unknown>> {
  if (!isRecord(value) || !isSafeArtifactDemoJsonValue(value, 0)) return false;
  try {
    return new TextEncoder().encode(canonicalJson(value)).byteLength <= 2_048;
  } catch {
    return false;
  }
}

function isSafeArtifactDemoJsonValue(value: unknown, depth: number): boolean {
  if (depth > 6) return false;
  if (value === null || typeof value === "boolean" || typeof value === "string") return true;
  if (typeof value === "number") return Number.isFinite(value) && Math.abs(value) <= Number.MAX_SAFE_INTEGER;
  if (Array.isArray(value)) return value.length <= 64 && value.every((item) => isSafeArtifactDemoJsonValue(item, depth + 1));
  if (!isRecord(value)) return false;
  const entries = Object.entries(value);
  return entries.length <= 64 && entries.every(([key, item]) =>
    new TextEncoder().encode(key).byteLength >= 1
    && new TextEncoder().encode(key).byteLength <= 160
    && isSafeArtifactDemoJsonValue(item, depth + 1));
}

function toTutorArtifactOptions(payload: unknown): Array<{ value: string; label: string }> | null {
  if (!Array.isArray(payload) || payload.length > 24) return null;
  const options: Array<{ value: string; label: string }> = [];
  for (const item of payload) {
    if (!isRecord(item) || !hasExactKeys(item, ["value", "label"]) ||
        !isArtifactBoundedString(item.value, 160) || !isArtifactBoundedString(item.label, 320)) return null;
    options.push({ value: item.value, label: item.label });
  }
  return new Set(options.map((item) => item.value)).size === options.length ? options : null;
}

function toKnowledgeCheckHints(payload: unknown): Array<{ level: 1 | 2 | 3; label: "方向" | "概念" | "结构"; markdown: string }> | null {
  if (!Array.isArray(payload) || payload.length > 3) return null;
  const hints: Array<{ level: 1 | 2 | 3; label: "方向" | "概念" | "结构"; markdown: string }> = [];
  const labels = ["方向", "概念", "结构"] as const;
  for (const [index, item] of payload.entries()) {
    if (!isRecord(item) || !hasExactKeys(item, ["level", "label", "markdown"]) || item.level !== index + 1 ||
        item.label !== labels[index] || !isArtifactBoundedString(item.markdown, 2_000)) return null;
    hints.push({ level: item.level as 1 | 2 | 3, label: labels[index], markdown: item.markdown });
  }
  return hints;
}

function toHintLevels(payload: unknown): Array<1 | 2 | 3> | null {
  if (!Array.isArray(payload) || payload.length > 3) return null;
  const levels: Array<1 | 2 | 3> = [];
  for (const [index, item] of payload.entries()) {
    if (item !== index + 1) return null;
    levels.push(item as 1 | 2 | 3);
  }
  return levels;
}

function toTutorArtifactActionKinds(payload: unknown): TutorArtifactActionKind[] | null {
  if (!Array.isArray(payload) || payload.length > 6 || !payload.every(isTutorArtifactActionKind)) return null;
  return new Set(payload).size === payload.length ? [...payload] : null;
}

function toTutorArtifactSourceReferences(payload: unknown): TutorArtifactSourceReference[] | null {
  if (!Array.isArray(payload) || payload.length > 12) return null;
  const references: TutorArtifactSourceReference[] = [];
  for (const item of payload) {
    if (!isRecord(item) || !hasExactKeys(item, ["kind", "reference_id", "reference_version", "content_hash", "label"]) ||
        !isTutorArtifactSourceReferenceKind(item.kind) || !isArtifactBoundedString(item.reference_id, 160) ||
        !(item.reference_version === null || isPositiveSafeInteger(item.reference_version)) ||
        !isNullableSha256(item.content_hash) || !isArtifactBoundedString(item.label, 240)) return null;
    references.push({ kind: item.kind, reference_id: item.reference_id, reference_version: item.reference_version,
      content_hash: item.content_hash, label: item.label });
  }
  const identities = references.map((item) => `${item.kind}\u0000${item.reference_id}\u0000${item.reference_version ?? ""}\u0000${item.content_hash ?? ""}`);
  return new Set(identities).size === identities.length ? references : null;
}

function toTutorArtifactAttemptSummary(payload: unknown): TutorArtifactAttemptSummary | null {
  if (!isRecord(payload) || !hasExactKeys(payload, [
    "attempt_id", "attempt_type", "status", "outcome", "score", "result_hash", "accepted_at", "terminal_at",
  ]) || !isArtifactBoundedString(payload.attempt_id, 160) || !isTutorArtifactAttemptType(payload.attempt_type) ||
      (payload.status !== "pending" && payload.status !== "terminal") || !isNullableTutorArtifactOutcome(payload.outcome) ||
      !(payload.score === null || isArtifactScore(payload.score)) || !isNullableSha256(payload.result_hash) ||
      !isArtifactBoundedString(payload.accepted_at, 80) || !isNullableArtifactBoundedString(payload.terminal_at, 80)) return null;
  const terminalFields = payload.outcome !== null && payload.score !== null && payload.result_hash !== null && payload.terminal_at !== null;
  if ((payload.status === "terminal") !== terminalFields) return null;
  return { attempt_id: payload.attempt_id, attempt_type: payload.attempt_type, status: payload.status,
    outcome: payload.outcome, score: payload.score, result_hash: payload.result_hash,
    accepted_at: payload.accepted_at, terminal_at: payload.terminal_at };
}

function toTutorArtifactAttemptDetail(payload: unknown): TutorArtifactAttemptDetail | null {
  if (!isRecord(payload) || hasProtectedArtifactData(payload) || !hasExactKeys(payload, [
    "schema_version", "artifact_id", "artifact_version", "conversation_id", "learning_track_id", "knowledge_key",
    "teaching_session_id", "attempt_id", "attempt_type", "exercise_version_id", "submission_hash", "independence",
    "assistance_kind", "status", "execution_job_state", "accepted_at", "result",
  ])) return null;
  const base = toTutorArtifactAttemptBase(payload);
  if (!base) return null;
  if (payload.schema_version === "tutor_learning_artifact_attempt_v1") {
    const result = payload.result === null ? null : toTutorArtifactAttemptResultV1(payload.result);
    if ((payload.result !== null && result === null) || ((base.status === "terminal") !== (result !== null))) return null;
    return { schema_version: "tutor_learning_artifact_attempt_v1", ...base, result };
  }
  if (payload.schema_version === "tutor_learning_artifact_attempt_v2") {
    const result = payload.result === null ? null : toTutorArtifactAttemptResultV2(payload.result);
    if ((payload.result !== null && result === null) || ((base.status === "terminal") !== (result !== null))) return null;
    return { schema_version: "tutor_learning_artifact_attempt_v2", ...base, result };
  }
  return null;
}

function toTutorArtifactAttemptBase(
  payload: Record<string, unknown>,
): Omit<TutorArtifactAttemptDetailV2, "schema_version" | "result"> | null {
  if (!isArtifactBoundedString(payload.artifact_id, 160) || !isPositiveSafeInteger(payload.artifact_version) ||
      !isArtifactBoundedString(payload.conversation_id, 160) || !isArtifactBoundedString(payload.learning_track_id, 160) ||
      !isArtifactStableKey(payload.knowledge_key) || !isArtifactBoundedString(payload.teaching_session_id, 160) ||
      !isArtifactBoundedString(payload.attempt_id, 160) || !isTutorArtifactAttemptType(payload.attempt_type) ||
      !isArtifactBoundedString(payload.exercise_version_id, 160) || !isSha256(payload.submission_hash) ||
      !isTutorArtifactAttemptIndependence(payload.independence) || !isModelReviewAssistanceKind(payload.assistance_kind) ||
      (payload.status !== "pending" && payload.status !== "terminal") || !isTutorArtifactExecutionJobState(payload.execution_job_state) ||
      !isArtifactBoundedString(payload.accepted_at, 80)) return null;
  return {
    artifact_id: payload.artifact_id,
    artifact_version: payload.artifact_version,
    conversation_id: payload.conversation_id,
    learning_track_id: payload.learning_track_id,
    knowledge_key: payload.knowledge_key,
    teaching_session_id: payload.teaching_session_id,
    attempt_id: payload.attempt_id,
    attempt_type: payload.attempt_type,
    exercise_version_id: payload.exercise_version_id,
    submission_hash: payload.submission_hash,
    independence: payload.independence,
    assistance_kind: payload.assistance_kind,
    status: payload.status,
    execution_job_state: payload.execution_job_state,
    accepted_at: payload.accepted_at,
  };
}

function toTutorArtifactAttemptResultV1(payload: unknown): TutorArtifactAttemptResultV1 | null {
  if (!isRecord(payload) || !hasExactKeys(payload, [
    "outcome", "score", "safe_feedback", "capability_scores", "policy_version", "result_hash", "terminal_at",
  ]) || !isTutorArtifactOutcome(payload.outcome) || !isArtifactScore(payload.score) || !isRecord(payload.safe_feedback) ||
      !isArtifactStableKey(payload.policy_version) || !isSha256(payload.result_hash) ||
      !isArtifactBoundedString(payload.terminal_at, 80)) return null;
  const capabilityScores = toTutorArtifactCapabilityScores(payload.capability_scores);
  if (!capabilityScores) return null;
  return {
    outcome: payload.outcome,
    score: payload.score,
    safe_feedback: payload.safe_feedback,
    capability_scores: capabilityScores,
    policy_version: payload.policy_version,
    result_hash: payload.result_hash,
    terminal_at: payload.terminal_at,
  };
}

function toTutorArtifactAttemptResultV2(payload: unknown): TutorArtifactAttemptResultV2 | null {
  if (!isRecord(payload) || !hasExactKeys(payload, [
    "outcome", "score", "execution_result", "capability_scores", "policy_version", "result_hash", "terminal_at",
  ]) || !isTutorArtifactOutcome(payload.outcome) || !isArtifactScore(payload.score) ||
      !isArtifactStableKey(payload.policy_version) || !isSha256(payload.result_hash) ||
      !isArtifactBoundedString(payload.terminal_at, 80)) return null;
  const executionResult = payload.execution_result === null ? null : toSafeExecutionResultV2(payload.execution_result);
  const capabilityScores = toTutorArtifactCapabilityScores(payload.capability_scores);
  if ((payload.execution_result !== null && executionResult === null) || !capabilityScores) return null;
  return {
    outcome: payload.outcome,
    score: payload.score,
    execution_result: executionResult,
    capability_scores: capabilityScores,
    policy_version: payload.policy_version,
    result_hash: payload.result_hash,
    terminal_at: payload.terminal_at,
  };
}

function toTutorArtifactCapabilityScores(payload: unknown): Readonly<Record<string, number>> | null {
  if (!isRecord(payload) || Object.keys(payload).length > 64) return null;
  const scores: Record<string, number> = {};
  for (const [key, value] of Object.entries(payload)) {
    if (!isArtifactStableKey(key) || typeof value !== "number" || !Number.isFinite(value)) return null;
    scores[key] = value;
  }
  return scores;
}

function toSafeExecutionResultV2(payload: unknown): SafeExecutionResultV2 | null {
  if (!isRecord(payload) || !hasExactKeys(payload, [
    "schema_version", "status", "stdout", "stderr", "test_feedback", "passed_test_count", "total_test_count",
    "duration_ms", "diagnostic_code", "presentation",
  ]) || payload.schema_version !== "safe-execution-result-v2" || !isSafeExecutionStatus(payload.status) ||
      !isExecutionString(payload.stdout, 4_000) || !isExecutionString(payload.stderr, 2_000) ||
      containsProtectedExecutionText(payload.stdout) || containsProtectedExecutionText(payload.stderr) ||
      !Array.isArray(payload.test_feedback) || payload.test_feedback.length > 64 ||
      !isArtifactIntegerInRange(payload.passed_test_count, 0, 10_000) ||
      !isArtifactIntegerInRange(payload.total_test_count, 0, 10_000) ||
      payload.passed_test_count > payload.total_test_count || payload.test_feedback.length > payload.total_test_count ||
      !isArtifactIntegerInRange(payload.duration_ms, 0, 120_000) || !isSafeExecutionIdentifier(payload.diagnostic_code, 120)) return null;
  const feedback: SafeTestFeedbackV2[] = [];
  for (const item of payload.test_feedback) {
    const parsed = toSafeTestFeedbackV2(item);
    if (!parsed) return null;
    feedback.push(parsed);
  }
  const identities = feedback.map((item) => item.case_id);
  if (new Set(identities).size !== identities.length) return null;
  let hiddenOrdinal = 0;
  let feedbackPassed = 0;
  for (const item of feedback) {
    feedbackPassed += item.passed ? 1 : 0;
    if (item.visible) continue;
    hiddenOrdinal += 1;
    const expectedMessage = item.passed
      ? "A non-visible scenario passed."
      : "A non-visible scenario still failed.";
    if (item.case_id !== `non-visible-${hiddenOrdinal}` || item.message !== expectedMessage) return null;
  }
  const feedbackFailed = feedback.length - feedbackPassed;
  if (feedbackPassed > payload.passed_test_count || feedbackFailed > payload.total_test_count - payload.passed_test_count) return null;
  const presentation = toSafeExecutionPresentation(payload.presentation);
  if (!presentation || (presentation.kind === "table_result_v1" && payload.status !== "success")) return null;
  return {
    schema_version: "safe-execution-result-v2",
    status: payload.status,
    stdout: payload.stdout,
    stderr: payload.stderr,
    test_feedback: feedback,
    passed_test_count: payload.passed_test_count,
    total_test_count: payload.total_test_count,
    duration_ms: payload.duration_ms,
    diagnostic_code: payload.diagnostic_code,
    presentation,
  };
}

function toSafeTestFeedbackV2(payload: unknown): SafeTestFeedbackV2 | null {
  if (!isRecord(payload) || !hasExactKeys(payload, [
    "case_id", "passed", "visible", "message", "duration_ms", "location",
  ]) || !isSafeExecutionIdentifier(payload.case_id, 120) || typeof payload.passed !== "boolean" ||
      typeof payload.visible !== "boolean" || !isExecutionString(payload.message, 320) ||
      !isArtifactIntegerInRange(payload.duration_ms, 0, 120_000)) return null;
  const location = payload.location === null ? null : toSafeExecutionLocation(payload.location);
  if ((payload.location !== null && location === null) || (!payload.visible && location !== null)) return null;
  if (payload.visible && (containsProtectedExecutionText(payload.case_id) || containsProtectedExecutionText(payload.message))) return null;
  return {
    case_id: payload.case_id,
    passed: payload.passed,
    visible: payload.visible,
    message: payload.message,
    duration_ms: payload.duration_ms,
    location,
  };
}

function toSafeExecutionLocation(payload: unknown): SafeExecutionLocation | null {
  if (!isRecord(payload) || !hasExactKeys(payload, ["line", "column", "end_line", "end_column"]) ||
      !isArtifactIntegerInRange(payload.line, 1, 1_000_000) ||
      !(payload.column === null || isArtifactIntegerInRange(payload.column, 1, 100_000)) ||
      !(payload.end_line === null || isArtifactIntegerInRange(payload.end_line, 1, 1_000_000)) ||
      !(payload.end_column === null || isArtifactIntegerInRange(payload.end_column, 1, 100_000))) return null;
  if ((payload.end_column !== null && payload.end_line === null) ||
      (payload.end_line !== null && payload.end_line < payload.line) ||
      (payload.end_line === payload.line && payload.column !== null && payload.end_column !== null && payload.end_column < payload.column)) return null;
  return { line: payload.line, column: payload.column, end_line: payload.end_line, end_column: payload.end_column };
}

function toSafeExecutionPresentation(payload: unknown): SafeExecutionPresentation | null {
  if (!isRecord(payload) || !isString(payload.kind)) return null;
  if (payload.kind === "none") return hasExactKeys(payload, ["kind"]) ? { kind: "none" } : null;
  if (payload.kind !== "table_result_v1" || !hasExactKeys(payload, ["kind", "columns", "rows"]) ||
      !Array.isArray(payload.columns) || payload.columns.length < 1 || payload.columns.length > 32 ||
      !payload.columns.every((column) => typeof column === "string" && isExecutionString(column, 120, true) &&
        !containsProtectedExecutionText(column)) || new Set(payload.columns).size !== payload.columns.length ||
      !Array.isArray(payload.rows) || payload.rows.length > 200) return null;
  const rows: Array<Array<string | number | boolean | null>> = [];
  for (const row of payload.rows) {
    if (!Array.isArray(row) || row.length !== payload.columns.length) return null;
    const cells: Array<string | number | boolean | null> = [];
    for (const cell of row) {
      if (!isSafeTableResultCell(cell)) return null;
      cells.push(cell);
    }
    rows.push(cells);
  }
  if (new TextEncoder().encode(JSON.stringify(payload)).length > 65_536) return null;
  return { kind: "table_result_v1", columns: [...payload.columns], rows };
}

function isSafeTableResultCell(value: unknown): value is string | number | boolean | null {
  if (value === null || typeof value === "boolean") return true;
  if (typeof value === "number") {
    return Number.isFinite(value) && Math.abs(value) <= Number.MAX_SAFE_INTEGER;
  }
  return typeof value === "string" && isExecutionString(value, 500) && !containsProtectedExecutionText(value);
}

function toTutorArtifactBranchSummary(payload: unknown): TutorArtifactBranchSummary | null {
  if (!isRecord(payload) || !hasExactKeys(payload, [
    "branch_id", "state", "disposition", "round_count", "item_count", "collapsed",
  ]) || !isArtifactBoundedString(payload.branch_id, 160) || (payload.state !== "active" && payload.state !== "resolved") ||
      !isNullableTutorBranchDisposition(payload.disposition) || !isArtifactIntegerInRange(payload.round_count, 1, 100) ||
      !isArtifactIntegerInRange(payload.item_count, 1, 400) || typeof payload.collapsed !== "boolean" ||
      payload.collapsed !== (payload.state === "resolved") || (payload.state === "resolved" && payload.disposition === null)) return null;
  return { branch_id: payload.branch_id, state: payload.state, disposition: payload.disposition,
    round_count: payload.round_count, item_count: payload.item_count, collapsed: payload.collapsed };
}

function toTutorPublicBranchGroup(payload: unknown): TutorPublicBranchGroup | null {
  if (!isRecord(payload) || !hasExactKeys(payload, [
    "schema_version", "branch_id", "anchor_artifact_id", "teaching_session_id", "checkpoint_id", "state",
    "disposition", "round_count", "item_count", "collapsed", "items", "created_at", "resolved_at",
  ]) || payload.schema_version !== "tutor_conversation_branch_v1" || !isArtifactBoundedString(payload.branch_id, 160) ||
      !isArtifactBoundedString(payload.anchor_artifact_id, 160) || !isArtifactBoundedString(payload.teaching_session_id, 160) ||
      !isArtifactBoundedString(payload.checkpoint_id, 160) || (payload.state !== "active" && payload.state !== "resolved") ||
      !isNullableTutorBranchDisposition(payload.disposition) || !isArtifactIntegerInRange(payload.round_count, 1, 100) ||
      !isArtifactIntegerInRange(payload.item_count, 1, 400) || typeof payload.collapsed !== "boolean" ||
      !Array.isArray(payload.items) || payload.items.length < 1 || payload.items.length > 400 ||
      !isArtifactBoundedString(payload.created_at, 80) || !isNullableArtifactBoundedString(payload.resolved_at, 80)) return null;
  const items = payload.items.map(toTutorPublicBranchItemReference);
  if (items.some((item) => item === null)) return null;
  const parsedItems = items.filter((item): item is TutorPublicBranchItemReference => item !== null);
  const identities = parsedItems.map((item) => `${item.item_kind}\u0000${item.item_id}`);
  const contiguous = parsedItems.every((item, index) => item.item_sequence === index + 1);
  const roundCount = payload.round_count;
  if ((payload.state === "resolved") !== (payload.resolved_at !== null) || payload.collapsed !== (payload.state === "resolved") ||
      payload.item_count !== parsedItems.length || !contiguous || new Set(identities).size !== identities.length ||
      parsedItems.some((item) => item.branch_round > roundCount) ||
      (payload.state === "resolved" && payload.disposition === null)) return null;
  return { schema_version: "tutor_conversation_branch_v1", branch_id: payload.branch_id,
    anchor_artifact_id: payload.anchor_artifact_id, teaching_session_id: payload.teaching_session_id,
    checkpoint_id: payload.checkpoint_id, state: payload.state, disposition: payload.disposition,
    round_count: payload.round_count, item_count: payload.item_count, collapsed: payload.collapsed,
    items: parsedItems, created_at: payload.created_at, resolved_at: payload.resolved_at };
}

function toTutorPublicBranchItemReference(payload: unknown): TutorPublicBranchItemReference | null {
  if (!isRecord(payload) || !hasExactKeys(payload, [
    "item_sequence", "branch_round", "item_kind", "item_id", "turn_id", "item_role",
  ]) || !isArtifactIntegerInRange(payload.item_sequence, 1, 400) || !isArtifactIntegerInRange(payload.branch_round, 1, 100) ||
      (payload.item_kind !== "message" && payload.item_kind !== "process") || !isArtifactBoundedString(payload.item_id, 160) ||
      !isArtifactBoundedString(payload.turn_id, 160) ||
      (payload.item_role !== "learner" && payload.item_role !== "tutor" && payload.item_role !== "process") ||
      (payload.item_kind === "process" && payload.item_role !== "process") ||
      (payload.item_kind === "message" && payload.item_role === "process")) return null;
  return { item_sequence: payload.item_sequence, branch_round: payload.branch_round, item_kind: payload.item_kind,
    item_id: payload.item_id, turn_id: payload.turn_id, item_role: payload.item_role };
}

function toTutorArtifactActionResponse(payload: unknown): TutorArtifactActionResponse | null {
  if (!isRecord(payload) || !hasExactKeys(payload, [
    "artifact", "artifact_event_id", "artifact_event_sequence", "idempotent_replayed",
  ]) || !isArtifactBoundedString(payload.artifact_event_id, 160) ||
      !isPositiveSafeInteger(payload.artifact_event_sequence) || typeof payload.idempotent_replayed !== "boolean") return null;
  const artifact = toTutorPublicArtifactItem(payload.artifact);
  if (!artifact || artifact.version !== payload.artifact_event_sequence) return null;
  return { artifact, artifact_event_id: payload.artifact_event_id,
    artifact_event_sequence: payload.artifact_event_sequence, idempotent_replayed: payload.idempotent_replayed };
}

function toTutorPublicProcess(payload: unknown): TutorPublicProcess | null {
  if (!isRecord(payload) || payload.kind !== "process") return null;
  const legacy = hasExactKeys(payload, [
    "kind", "id", "run_id", "display_state", "steps", "elapsed_seconds", "created_at", "finished_at",
  ]);
  const snapshot = hasExactKeys(payload, [
    "kind", "id", "turn_id", "run_id", "display_state", "steps", "elapsed_seconds", "created_at", "finished_at",
  ]);
  if ((!legacy && !snapshot) || !isBoundedString(payload.id, 120) || !isBoundedString(payload.run_id, 120) ||
      (snapshot && !isBoundedString(payload.turn_id, 120)) || !isTutorProcessDisplayState(payload.display_state) ||
      !Array.isArray(payload.steps) || payload.steps.length > 16 || !isNonNegativeSafeInteger(payload.elapsed_seconds) ||
      payload.elapsed_seconds > 3_600 || !isNullableBoundedString(payload.created_at, 80) ||
      !isNullableBoundedString(payload.finished_at, 80)) return null;
  const steps: TutorPublicProcessStep[] = [];
  for (const step of payload.steps) {
    const parsed = toTutorPublicProcessStep(step);
    if (!parsed) return null;
    steps.push(parsed);
  }
  const turnId = snapshot && isBoundedString(payload.turn_id, 120) ? payload.turn_id : null;
  return {
    kind: "process",
    id: payload.id,
    turn_id: turnId,
    run_id: payload.run_id,
    display_state: payload.display_state,
    steps,
    elapsed_seconds: payload.elapsed_seconds,
    created_at: payload.created_at,
    finished_at: payload.finished_at,
  };
}

function toTutorPublicProcessStep(payload: unknown): TutorPublicProcessStep | null {
  if (!isRecord(payload) || !hasExactKeys(payload, ["key", "state", "label"]) ||
      !isTutorProcessStepKey(payload.key) || !isTutorProcessStepState(payload.state) ||
      !isBoundedString(payload.label, 160)) return null;
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
  if (hasProtectedArtifactMarker(payload)) return null;
  if (!isRecord(payload) || !isTutorConversationSnapshotVersion(payload.snapshot_version)) return null;
  const version = payload.snapshot_version;
  const baseKeys = [
    "snapshot_version", "conversation", "active_turn", "active_thinking", "pending_requests", "queue", "timeline",
    "next_cursor", "has_more", "stream_cursor",
  ];
  if (version !== "tutor_conversation_snapshot_v2") baseKeys.push("active_runtime_output");
  if (version === "tutor_conversation_snapshot_v4" || version === "tutor_conversation_snapshot_v5") baseKeys.push("active_artifact");
  if (version === "tutor_conversation_snapshot_v5") baseKeys.push("branches");
  const expectedKeys = "teaching_sessions" in payload ? [...baseKeys, "teaching_sessions"] : baseKeys;
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
  const teachingSessions = "teaching_sessions" in payload && Array.isArray(payload.teaching_sessions)
    ? payload.teaching_sessions.map(toTeachingSessionGroupProjection)
    : [];
  const teachingTurnIds = teachingSessions.flatMap((item) => item?.turn_ids ?? []);
  const timelineIdentities = timeline.map((item) => item === null ? null : `${item.kind}\u0000${item.id}`);
  if (pendingRequests.some((item) => item === null) || queue.some((item) => item === null) || timeline.some((item) => item === null) ||
      teachingSessions.some((item) => item === null) || teachingSessions.length > 50 ||
      new Set(teachingTurnIds).size !== teachingTurnIds.length || timelineIdentities.some((item) => item === null) ||
      new Set(timelineIdentities).size !== timelineIdentities.length) return null;
  const activeTurn = payload.active_turn === null ? null : toTutorPublicTurn(payload.active_turn);
  const activeThinking = payload.active_thinking === null ? null : toTutorActiveThinking(payload.active_thinking);
  const activeRuntimeOutput = version !== "tutor_conversation_snapshot_v2" && payload.active_runtime_output !== null
    ? toTutorRuntimeOutput(payload.active_runtime_output)
    : null;
  const activeArtifact = (version === "tutor_conversation_snapshot_v4" || version === "tutor_conversation_snapshot_v5") && payload.active_artifact !== null
    ? toTutorPublicArtifactItem(payload.active_artifact)
    : null;
  const branches = version === "tutor_conversation_snapshot_v5" && Array.isArray(payload.branches)
    ? payload.branches.map(toTutorPublicBranchGroup)
    : [];
  const parsedTimeline = timeline.filter((item): item is TutorHistoryItem => item !== null);
  const parsedBranches = branches.filter((item): item is TutorPublicBranchGroup => item !== null);
  if ((activeTurn === null && payload.active_turn !== null) ||
      (activeThinking === null && payload.active_thinking !== null) ||
      (version !== "tutor_conversation_snapshot_v2" && payload.active_runtime_output !== null && activeRuntimeOutput === null) ||
      ((version === "tutor_conversation_snapshot_v4" || version === "tutor_conversation_snapshot_v5") && payload.active_artifact !== null && activeArtifact === null) ||
      (version === "tutor_conversation_snapshot_v5" && (!Array.isArray(payload.branches) || branches.some((item) => item === null) || parsedBranches.length === 0)) ||
      (activeThinking !== null && (activeTurn === null || activeThinking.turn_id !== activeTurn.turn_id || activeThinking.input_revision !== activeTurn.input_revision)) ||
      (activeRuntimeOutput !== null && (activeTurn === null || activeRuntimeOutput.input_revision !== activeTurn.input_revision)) ||
      (activeTurn !== null && activeTurn.conversation_id !== payload.conversation.conversation_id) ||
      !validateTutorSnapshotArtifactProjection(version, payload.conversation.conversation_id, parsedTimeline, activeArtifact, parsedBranches)) return null;
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
    active_artifact: activeArtifact,
    branches: parsedBranches,
    pending_requests: pendingRequests.filter((item): item is TutorInteractionRequestItem => item !== null),
    queue: queue.filter((item): item is TutorQueuedInput => item !== null),
    timeline: parsedTimeline,
    next_cursor: payload.next_cursor,
    has_more: payload.has_more,
    stream_cursor: payload.stream_cursor,
    teaching_sessions: teachingSessions.filter((item): item is TeachingSessionGroupProjection => item !== null),
  };
}

function validateTutorSnapshotArtifactProjection(
  version: TutorConversationSnapshotResponse["snapshot_version"],
  conversationId: string,
  timeline: TutorHistoryItem[],
  activeArtifact: TutorPublicArtifactItem | null,
  branches: TutorPublicBranchGroup[],
): boolean {
  const artifacts = timeline.filter((item): item is TutorPublicArtifactItem => item.kind === "artifact");
  if (artifacts.some((item) => item.conversation_id !== conversationId)) return false;
  if ((version === "tutor_conversation_snapshot_v2" || version === "tutor_conversation_snapshot_v3") &&
      (artifacts.length > 0 || activeArtifact !== null || branches.length > 0)) return false;
  if (version === "tutor_conversation_snapshot_v4" &&
      (branches.length > 0 || artifacts.some((item) => item.branch_summary !== null) ||
       (activeArtifact !== null && activeArtifact.branch_summary !== null))) return false;

  const artifactById = new Map<string, TutorPublicArtifactItem>();
  for (const artifact of artifacts) artifactById.set(artifact.id, artifact);
  if (activeArtifact !== null) {
    if (activeArtifact.conversation_id !== conversationId || !activeArtifact.blocking || isTutorArtifactTerminalState(activeArtifact.state)) return false;
    const timelineArtifact = artifactById.get(activeArtifact.id);
    if (timelineArtifact && JSON.stringify(timelineArtifact) !== JSON.stringify(activeArtifact)) return false;
  }
  const blocking = artifacts.filter((item) => item.blocking && !isTutorArtifactTerminalState(item.state));
  if (blocking.length > 1 || (blocking.length === 1 && activeArtifact?.id !== blocking[0].id)) return false;

  const branchIds = branches.map((item) => item.branch_id);
  const branchItemIdentities = branches.flatMap((branch) => branch.items.map((item) => `${item.item_kind}\u0000${item.item_id}`));
  if (new Set(branchIds).size !== branchIds.length || new Set(branchItemIdentities).size !== branchItemIdentities.length) return false;
  const branchById = new Map(branches.map((item) => [item.branch_id, item]));
  const activeBranches = branches.filter((item) => item.state === "active");
  const activeAnchors = activeBranches.map((item) => item.anchor_artifact_id);
  if (activeBranches.length > 1 || new Set(activeAnchors).size !== activeAnchors.length) return false;

  const timelineByIdentity = new Map(timeline.map((item) => [`${item.kind}\u0000${item.id}`, item]));
  for (const branch of branches) {
    const anchor = artifactById.get(branch.anchor_artifact_id) ?? (activeArtifact?.id === branch.anchor_artifact_id ? activeArtifact : null);
    if (anchor) {
      if (anchor.teaching_session_id !== branch.teaching_session_id || anchor.checkpoint_id !== branch.checkpoint_id) return false;
      const summary = anchor.branch_summary;
      if (!summary || summary.branch_id !== branch.branch_id || summary.state !== branch.state ||
          summary.disposition !== branch.disposition || summary.round_count !== branch.round_count ||
          summary.item_count !== branch.item_count || summary.collapsed !== branch.collapsed) return false;
    }
    for (const reference of branch.items) {
      const item = timelineByIdentity.get(`${reference.item_kind}\u0000${reference.item_id}`);
      if (!item) continue;
      if (item.kind === "message" && (item.turn_id !== reference.turn_id || item.role !== reference.item_role)) return false;
      if (item.kind === "process" && (item.turn_id !== reference.turn_id || reference.item_role !== "process")) return false;
    }
  }

  const artifactsWithSummary = [...artifacts, ...(activeArtifact && !artifactById.has(activeArtifact.id) ? [activeArtifact] : [])];
  for (const artifact of artifactsWithSummary) {
    const summary = artifact.branch_summary;
    if (summary === null) continue;
    const branch = branchById.get(summary.branch_id);
    if (!branch || branch.anchor_artifact_id !== artifact.id || branch.state !== summary.state ||
        branch.disposition !== summary.disposition || branch.round_count !== summary.round_count ||
        branch.item_count !== summary.item_count || branch.collapsed !== summary.collapsed) return false;
  }
  return true;
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
  if (hasProtectedArtifactMarker(payload)) return null;
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
    if (payload.type === "single_select" && hasRequiredAndOptionalKeys(
      payload,
      ["type", "field_key", "options", "recommended"],
      ["selection_scope", "selection_reason_code", "intent_policy_version"],
    ) && isNullableString(payload.recommended)) {
      const selectionScope = payload.selection_scope ?? null;
      const selectionReasonCode = payload.selection_reason_code ?? null;
      const intentPolicyVersion = payload.intent_policy_version ?? null;
      if (!isNullablePlanningSelectionScope(selectionScope) || !isNullableString(selectionReasonCode) || !isNullableString(intentPolicyVersion)) return null;
      return {
        type: "single_select",
        field_key: payload.field_key,
        options: validOptions,
        recommended: payload.recommended,
        selection_scope: selectionScope,
        selection_reason_code: selectionReasonCode,
        intent_policy_version: intentPolicyVersion,
      };
    }
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

function hasProtectedArtifactMarker(value: unknown): boolean {
  if (typeof value === "string") {
    const normalized = value.toLowerCase();
    return ARTIFACT_PROTECTED_MARKERS.some((marker) => normalized.includes(marker.toLowerCase()));
  }
  if (Array.isArray(value)) return value.some(hasProtectedArtifactMarker);
  if (!isRecord(value)) return false;
  return Object.values(value).some(hasProtectedArtifactMarker);
}

function hasProtectedArtifactData(value: unknown): boolean {
  if (hasProtectedArtifactMarker(value)) return true;
  if (Array.isArray(value)) return value.some(hasProtectedArtifactData);
  if (!isRecord(value)) return false;
  return Object.entries(value).some(([key, item]) => ARTIFACT_PROTECTED_KEYS.has(key.toLowerCase()) || hasProtectedArtifactData(item));
}

function isArtifactString(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.length <= maximum;
}

function isArtifactBoundedString(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maximum;
}

function isNullableArtifactBoundedString(value: unknown, maximum: number): value is string | null {
  return value === null || isArtifactBoundedString(value, maximum);
}

function isNullableLearningItemHandle(value: unknown): value is string | null {
  return value === null || typeof value === "string" && /^li:[0-9a-f]{64}$/.test(value);
}

function isArtifactStableKey(value: unknown): value is string {
  return typeof value === "string" && /^[a-z0-9][a-z0-9._:-]{0,159}$/.test(value);
}

function isNullableArtifactStableKey(value: unknown): value is string | null {
  return value === null || isArtifactStableKey(value);
}

function isArtifactIntegerInRange(value: unknown, minimum: number, maximum: number): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= minimum && value <= maximum;
}

function isArtifactScore(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
}

function isNullableSha256(value: unknown): value is string | null {
  return value === null || isSha256(value);
}

function isTutorArtifactKind(value: unknown): value is TutorArtifactKind {
  return value === "exercise_workspace" || value === "browser_preview" || value === "test_result" ||
    value === "knowledge_check" || value === "model_code_review" || value === "sql_workspace" ||
    value === "demonstration" || value === "source_inspector";
}

function isTutorArtifactPurpose(value: unknown): value is TutorArtifactPurpose {
  return value === "exercise" || value === "demonstration" || value === "knowledge_check" || value === "remediation" ||
    value === "transfer_check" || value === "code_review" || value === "sql_exploration" || value === "result";
}

function isTutorArtifactOwnerKind(value: unknown): value is TutorArtifactOwnerKind {
  return value === "lesson_gate" || value === "review_item" || value === "teaching_practice" || value === "learning_item";
}

function isTutorArtifactState(value: unknown): value is TutorArtifactState {
  return value === "pending" || value === "ready" || value === "active" || value === "running" ||
    value === "completed" || value === "failed" || value === "cancelled" || value === "superseded";
}

function isTutorArtifactTerminalState(value: TutorArtifactState): boolean {
  return value === "completed" || value === "failed" || value === "cancelled" || value === "superseded";
}

function isTutorArtifactDifficulty(value: unknown): value is TutorArtifactDifficulty {
  return value === "D1" || value === "D2" || value === "D3" || value === "D4" || value === "D5";
}

function isTutorArtifactActionKind(value: unknown): value is TutorArtifactActionKind {
  return value === "request_hint" || value === "request_direct_answer" || value === "run" || value === "respond" || value === "complete_review" ||
    value === "cancel" || value === "acknowledge_demo_event" || value === "complete_demo";
}

function isTutorArtifactOutcome(value: unknown): value is TutorArtifactOutcome {
  return value === "passed" || value === "failed" || value === "timed_out" || value === "cancelled" ||
    value === "unavailable" || value === "invalid";
}

function isNullableTutorArtifactOutcome(value: unknown): value is TutorArtifactOutcome | null {
  return value === null || isTutorArtifactOutcome(value);
}

function isKnowledgeCheckAssistanceKind(value: unknown): value is "independent" | "hinted" | "direct_answer" | "remediated" | null {
  return value === null || value === "independent" || value === "hinted" || value === "direct_answer" || value === "remediated";
}

function isTutorArtifactResponseKind(value: unknown): value is Extract<TutorArtifactPresentation, { type: "knowledge_check_v1" }>["response_kind"] {
  return value === "single_select" || value === "multi_select" || value === "prediction" || value === "ordering" ||
    value === "code_range" || value === "short_text";
}

function isTutorArtifactSourceReferenceKind(value: unknown): value is TutorArtifactSourceReference["kind"] {
  return value === "lesson_document" || value === "exercise_version" || value === "attempt_result" ||
    value === "review_session" || value === "teaching_checkpoint" || value === "source_citation" || value === "artifact";
}

function isTutorArtifactAttemptType(value: unknown): value is TutorArtifactAttemptSummary["attempt_type"] {
  return value === "run" || value === "submit" || value === "diagnostic_submit" || value === "review_submit";
}

function isTutorArtifactAttemptIndependence(
  value: unknown,
): value is TutorArtifactAttemptDetailV2["independence"] {
  return value === "independent" || value === "hinted" || value === "remediated";
}

function isTutorArtifactExecutionJobState(
  value: unknown,
): value is TutorArtifactAttemptDetailV2["execution_job_state"] {
  return value === null || value === "pending" || value === "claimed" || value === "launch_reserved" ||
    value === "running" || value === "completed" || value === "timed_out" || value === "cancelled" ||
    value === "unavailable" || value === "launch_uncertain" || value === "failed";
}

function isSafeExecutionStatus(value: unknown): value is SafeExecutionResultV2["status"] {
  return value === "success" || value === "compile_error" || value === "runtime_error" || value === "timeout" ||
    value === "cancelled" || value === "unsupported" || value === "unavailable" || value === "failed";
}

function isSafeExecutionIdentifier(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maximum &&
    /^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$/.test(value);
}

function containsProtectedExecutionText(value: string): boolean {
  return value.includes("\0") || value.split(/\r?\n/).some((line) => SAFE_EXECUTION_PROTECTED_LINE.test(line));
}

function isExecutionString(value: unknown, maximum: number, required = false): value is string {
  if (typeof value !== "string") return false;
  const length = Array.from(value).length;
  return length <= maximum && (!required || length > 0);
}

function isNullableTutorBranchDisposition(value: unknown): value is TutorBranchResponseDisposition | null {
  return value === null || value === "answer_and_refocus" || value === "offer_switch" || value === "confirmed_switch";
}

function isTutorConversationSnapshotVersion(value: unknown): value is TutorConversationSnapshotResponse["snapshot_version"] {
  return value === "tutor_conversation_snapshot_v2" || value === "tutor_conversation_snapshot_v3" ||
    value === "tutor_conversation_snapshot_v4" || value === "tutor_conversation_snapshot_v5";
}

function doesTutorArtifactKindMatchPresentation(kind: TutorArtifactKind, presentation: TutorArtifactPresentation["type"]): boolean {
  return (kind === "exercise_workspace" && presentation === "exercise_workspace_v1") ||
    (kind === "browser_preview" && presentation === "browser_preview_v1") ||
    (kind === "test_result" && presentation === "test_result_v1") ||
    (kind === "knowledge_check" && presentation === "knowledge_check_v1") ||
    (kind === "model_code_review" && (presentation === "model_code_review_v1" || presentation === "model_code_review_v2")) ||
    (kind === "sql_workspace" && presentation === "sql_workspace_v1") ||
    (kind === "demonstration" && (presentation === "demonstration_v1" || presentation === "demonstration_v2")) ||
    (kind === "source_inspector" && presentation === "source_inspector_v1");
}

function toArtifactStableKeyArray(value: unknown, maximumLength: number): string[] | null {
  if (!Array.isArray(value) || value.length > maximumLength || !value.every(isArtifactStableKey)) return null;
  return new Set(value).size === value.length ? [...value] : null;
}

function toArtifactBoundedStringArray(value: unknown, maximumLength: number, maximumItemLength: number): string[] | null {
  if (!Array.isArray(value) || value.length > maximumLength ||
      !value.every((item) => isArtifactBoundedString(item, maximumItemLength))) return null;
  return new Set(value).size === value.length ? [...value] : null;
}

function normalizeArtifactNewlines(value: string): string {
  return value.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

function pythonSplitlines(value: string): string[] {
  if (value.length === 0) return [];
  const lines = value.split(/[\n\v\f\x1c-\x1e\x85\u2028\u2029]/);
  if (/[\n\v\f\x1c-\x1e\x85\u2028\u2029]$/.test(value)) lines.pop();
  return lines;
}

function pythonSplitlinesCount(value: string): number {
  return pythonSplitlines(value).length;
}

function sha256Text(value: string): string {
  const constants = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ];
  const bytes = new TextEncoder().encode(value);
  const paddedLength = Math.ceil((bytes.length + 9) / 64) * 64;
  const padded = new Uint8Array(paddedLength);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  let bitLength = BigInt(bytes.length) * 8n;
  for (let index = 0; index < 8; index += 1) {
    padded[padded.length - 1 - index] = Number(bitLength & 0xffn);
    bitLength >>= 8n;
  }
  const hashes = [
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ];
  const words = new Uint32Array(64);
  for (let offset = 0; offset < padded.length; offset += 64) {
    for (let index = 0; index < 16; index += 1) {
      const start = offset + index * 4;
      words[index] = ((padded[start] << 24) | (padded[start + 1] << 16) | (padded[start + 2] << 8) | padded[start + 3]) >>> 0;
    }
    for (let index = 16; index < 64; index += 1) {
      const previous15 = words[index - 15];
      const previous2 = words[index - 2];
      const sigma0 = (rotateRight(previous15, 7) ^ rotateRight(previous15, 18) ^ (previous15 >>> 3)) >>> 0;
      const sigma1 = (rotateRight(previous2, 17) ^ rotateRight(previous2, 19) ^ (previous2 >>> 10)) >>> 0;
      words[index] = (words[index - 16] + sigma0 + words[index - 7] + sigma1) >>> 0;
    }
    let [a, b, c, d, e, f, g, h] = hashes;
    for (let index = 0; index < 64; index += 1) {
      const sum1 = (rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25)) >>> 0;
      const choice = ((e & f) ^ (~e & g)) >>> 0;
      const temp1 = (h + sum1 + choice + constants[index] + words[index]) >>> 0;
      const sum0 = (rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22)) >>> 0;
      const majority = ((a & b) ^ (a & c) ^ (b & c)) >>> 0;
      const temp2 = (sum0 + majority) >>> 0;
      h = g; g = f; f = e; e = (d + temp1) >>> 0; d = c; c = b; b = a; a = (temp1 + temp2) >>> 0;
    }
    hashes[0] = (hashes[0] + a) >>> 0;
    hashes[1] = (hashes[1] + b) >>> 0;
    hashes[2] = (hashes[2] + c) >>> 0;
    hashes[3] = (hashes[3] + d) >>> 0;
    hashes[4] = (hashes[4] + e) >>> 0;
    hashes[5] = (hashes[5] + f) >>> 0;
    hashes[6] = (hashes[6] + g) >>> 0;
    hashes[7] = (hashes[7] + h) >>> 0;
  }
  return hashes.map((item) => item.toString(16).padStart(8, "0")).join("");
}

function rotateRight(value: number, count: number): number {
  return (value >>> count) | (value << (32 - count));
}

function isNullablePlanningSelectionScope(
  value: unknown,
): value is "explicit_shortlist" | "intent_shortlist" | "conflict_shortlist" | "full_catalog" | null {
  return value === null || value === "explicit_shortlist" || value === "intent_shortlist" ||
    value === "conflict_shortlist" || value === "full_catalog";
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
