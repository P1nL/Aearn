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
  LessonDocumentReferenceAssignment,
  LessonDocumentReferenceResolution,
  LessonDocumentReferenceSource,
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
  TutorActivityItem,
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

export async function fetchLessonDocumentReference(input: {
  userId: string;
  trackId: string;
  conversationId: string;
  knowledgeKey: string;
  source: LessonDocumentReferenceSource;
  signal?: AbortSignal;
}): Promise<LessonDocumentReferenceResolution> {
  const url = API_BASE_URL + "/api/learning-tracks/" + encodeURIComponent(input.trackId) +
    "/lesson-references/" + encodeURIComponent(input.conversationId) + "/resolve";
  const payload = await requestJson(url, {
    method: "POST",
    body: JSON.stringify({
      user_id: input.userId,
      knowledge_key: input.knowledgeKey,
      source: input.source,
    }),
    signal: input.signal,
  });
  const reference = toLessonDocumentReferenceResolution(payload);
  if (!reference || reference.learning_track_id !== input.trackId ||
      reference.conversation_id !== input.conversationId || reference.knowledge_key !== input.knowledgeKey ||
      reference.source_kind !== input.source.kind || !referenceMatchesRequestedSource(reference, input.source)) {
    throw new Error("Lesson document reference API returned an invalid payload");
  }
  return reference;
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


const LEARNING_TRACK_SUMMARY_KEYS = [
  "track_id", "language_id", "language_display_name", "goal_text", "target_level", "status", "version",
  "active_revision_id", "active_plan_title", "current_knowledge_key", "current_knowledge_title", "progress",
  "review_due_count", "execution_tier", "execution_disclosure", "last_learned_at", "updated_at",
] as const;

export function toLearningTrackDetail(payload: unknown): LearningTrackDetail | null {
  if (!isRecord(payload) || !hasExactKeys(payload, [...LEARNING_TRACK_SUMMARY_KEYS, "created_at", "archived_at"])) return null;
  const summary = toLearningTrackSummaryRecord(payload, false);
  if (!summary || !isNullableString(payload.created_at) || !isNullableString(payload.archived_at)) return null;
  return { ...summary, created_at: payload.created_at, archived_at: payload.archived_at };
}

export function toLearningRoadmap(payload: unknown): LearningRoadmap | null {
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

export function toLearningRoadmapModule(payload: unknown): LearningRoadmapModule | null {
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

export function toLearningRoadmapNode(payload: unknown): LearningRoadmapNode | null {
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


export function toLearningTrackSummary(payload: unknown): LearningTrackSummary | null {
  return toLearningTrackSummaryRecord(payload, true);
}

export function toLearningTrackSummaryRecord(payload: unknown, requireExact: boolean): LearningTrackSummary | null {
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

export function toLessonDocumentState(payload: unknown): LessonDocumentState | null {
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
    if (citationIds.size !== sources.length) return null;
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

export function toLessonDocumentReferenceResolution(payload: unknown): LessonDocumentReferenceResolution | null {
  if (!isRecord(payload) || !hasExactKeys(payload, [
    "schema_version", "source_kind", "source_id", "conversation_id", "learning_track_id",
    "knowledge_key", "reference_status", "assignment", "current_assignment", "document", "sources", "target",
  ]) || payload.schema_version !== "lesson_document_reference_v1" ||
      (payload.source_kind !== "lesson_block" && payload.source_kind !== "context_reference" && payload.source_kind !== "artifact") ||
      !isString(payload.source_id) || !payload.source_id || !isString(payload.conversation_id) || !isString(payload.learning_track_id) ||
      !isString(payload.knowledge_key) || (payload.reference_status !== "current" && payload.reference_status !== "historical")) return null;
  const assignment = toLessonDocumentReferenceAssignment(payload.assignment);
  const currentAssignment = payload.current_assignment === null ? null : toLessonDocumentReferenceAssignment(payload.current_assignment);
  const document = toLessonDocument(payload.document);
  if (!assignment || (payload.current_assignment !== null && !currentAssignment) || !document || !Array.isArray(payload.sources) || !isRecord(payload.target)) return null;
  const sources = payload.sources.map(toLessonCitation);
  const target = payload.target;
  if (sources.some((item) => item === null) || !hasExactKeys(target, [
    "block_id", "block_content_hash", "safe_excerpt", "citation_ids", "selected_citation_id",
  ]) || !isString(target.block_id) || !isSha256(target.block_content_hash) ||
      !isString(target.safe_excerpt) || target.safe_excerpt.length > 800 || !isStringArray(target.citation_ids) ||
      !isNullableString(target.selected_citation_id) || new Set(target.citation_ids).size !== target.citation_ids.length) return null;
  const validSources = sources.filter((item): item is LessonCitation => item !== null);
  const sourceIds = new Set(validSources.map((item) => item.citation_id));
  const block = document.blocks.find((item) => item.block_id === target.block_id);
  if (!block || document.knowledge_key !== payload.knowledge_key || sourceIds.size !== validSources.length ||
      target.citation_ids.some((id) => !block.citation_ids.includes(id) || !sourceIds.has(id)) ||
      (target.selected_citation_id !== null && (!target.citation_ids.includes(target.selected_citation_id) || !sourceIds.has(target.selected_citation_id)))) return null;
  if (assignment.content_hash !== document.content_hash ||
      (currentAssignment !== null && currentAssignment.status !== "active") ||
      (payload.reference_status === "current" && (assignment.status !== "active" || !currentAssignment || !sameReferenceAssignment(currentAssignment, assignment)))) return null;
  return {
    schema_version: "lesson_document_reference_v1",
    source_kind: payload.source_kind,
    source_id: payload.source_id,
    conversation_id: payload.conversation_id,
    learning_track_id: payload.learning_track_id,
    knowledge_key: payload.knowledge_key,
    reference_status: payload.reference_status,
    assignment,
    current_assignment: currentAssignment,
    document,
    sources: validSources,
    target: {
      block_id: target.block_id,
      block_content_hash: target.block_content_hash,
      safe_excerpt: target.safe_excerpt,
      citation_ids: target.citation_ids,
      selected_citation_id: target.selected_citation_id,
    },
  };
}

function referenceMatchesRequestedSource(
  reference: LessonDocumentReferenceResolution,
  source: LessonDocumentReferenceSource,
): boolean {
  if (source.kind === "context_reference") return reference.source_id === source.reference_id;
  if (source.kind === "artifact") return reference.source_id === source.artifact_id;
  return reference.source_id === source.document_id + ":" + source.block_id &&
    reference.assignment.document_id === source.document_id &&
    reference.assignment.content_hash === source.document_content_hash &&
    reference.assignment.assignment_version === source.assignment_version &&
    reference.target.block_id === source.block_id &&
    reference.target.selected_citation_id === source.citation_id;
}

function sameReferenceAssignment(
  left: LessonDocumentReferenceAssignment,
  right: LessonDocumentReferenceAssignment,
): boolean {
  return left.assignment_id === right.assignment_id && left.document_id === right.document_id &&
    left.assignment_version === right.assignment_version && left.status === right.status &&
    left.content_hash === right.content_hash;
}

function toLessonDocumentReferenceAssignment(payload: unknown): LessonDocumentReferenceAssignment | null {
  if (!isRecord(payload) || !hasExactKeys(payload, [
    "assignment_id", "document_id", "assignment_version", "status", "content_hash",
  ]) || !isString(payload.assignment_id) || !isString(payload.document_id) ||
      !isPositiveSafeInteger(payload.assignment_version) || !isLessonAssignmentStatus(payload.status) ||
      !isSha256(payload.content_hash)) return null;
  return {
    assignment_id: payload.assignment_id,
    document_id: payload.document_id,
    assignment_version: payload.assignment_version,
    status: payload.status,
    content_hash: payload.content_hash,
  };
}

export function toLessonPrepareResponse(payload: unknown): LessonPrepareResponse | null {
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

export function toLessonGateList(payload: unknown): LessonGateList | null {
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

export function toLessonGatePrepareResponse(payload: unknown): LessonGatePrepareResponse | null {
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

export function toModelReviewAuthoringRun(payload: unknown): ModelReviewAuthoringRun | null {
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

export function toModelReviewEvidenceResponse(payload: unknown): ModelReviewEvidenceResponse | null {
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

export function toModelReviewVisibleEvidence(payload: unknown): ModelReviewVisibleEvidence | null {
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

export function toLessonGateHint(payload: unknown): LessonGateHint | null {
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

export function toLessonGateItem(payload: unknown): LessonGateItem | null {
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

export function toLessonGateExercise(payload: unknown, requireGateFields: boolean): LessonGateExercise | null {
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

export function toLessonGateResult(payload: unknown): LessonGateResult | null {
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

export function toModelReviewPrompt(payload: unknown): ModelReviewPrompt | null {
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

export function toModelReviewArtifact(payload: unknown): ModelReviewArtifact | null {
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

export function toModelReviewSafeFeedback(payload: unknown): ModelReviewSafeFeedback | null {
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

export function toModelReviewScoreBreakdown(payload: unknown): ModelReviewScoreBreakdown | null {
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

export function toModelReviewFindingFeedback(payload: unknown): ModelReviewFindingFeedback | null {
  if (
    !isRecord(payload) || !hasExactKeys(payload, ["client_finding_id", "status", "safe_reason_code"]) ||
    !isString(payload.client_finding_id) || !isModelReviewFindingStatus(payload.status) || !isString(payload.safe_reason_code)
  ) return null;
  return { client_finding_id: payload.client_finding_id, status: payload.status, safe_reason_code: payload.safe_reason_code };
}

export function toExerciseAttemptState(payload: unknown): ExerciseAttemptState | null {
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

export function toExerciseMastery(payload: unknown): ExerciseAttemptState["mastery"] | null {
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

export function toModuleDiagnosticState(payload: unknown): ModuleDiagnosticState | null {
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

export function toModuleDiagnosticItem(payload: unknown): ModuleDiagnosticItem | null {
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

export function toModuleDiagnosticImpact(payload: unknown): ModuleDiagnosticImpact | null | undefined {
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

export function toLessonDocument(payload: unknown): LessonDocument | null {
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

export function toLessonBlock(payload: unknown): LessonBlock | null {
  if (
    !isRecord(payload) || !isString(payload.block_id) ||
    !isNonNegativeSafeInteger(payload.order_index) || !isStringArray(payload.citation_ids) ||
    new Set(payload.citation_ids).size !== payload.citation_ids.length ||
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

export function toLessonCitation(payload: unknown): LessonCitation | null {
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

export function toLessonAssignment(payload: unknown): LessonAssignment | null {
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

export function toLessonAuthoringRun(payload: unknown): LessonAuthoringRun | null {
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

export function toLessonUpdateProposal(payload: unknown): LessonUpdateProposal | null {
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

export function isLessonPublicStatus(value: unknown): value is LessonDocumentState["status"] {
  return value === "missing" || value === "preparing" || value === "ready" || value === "failed";
}
export function isLessonAssignmentStatus(value: unknown): value is LessonAssignment["status"] {
  return value === "active" || value === "proposed" || value === "superseded";
}
export function isLessonAuthoringState(value: unknown): value is LessonAuthoringRun["state"] {
  return value === "pending" || value === "claimed" || value === "running" || value === "completed" || value === "failed" || value === "cancelled";
}
export function isLessonGateKind(value: unknown): value is "knowledge_check" | "guided_practice" | "independent_practice" {
  return value === "knowledge_check" || value === "guided_practice" || value === "independent_practice";
}
export function isLessonTrustTier(value: unknown): value is LessonCitation["trust_tier"] {
  return value === "official" || value === "trusted_de_facto" || value === "internal";
}
export function isLessonSourceType(value: unknown): value is LessonCitation["source_type"] {
  return value === "tutorial" || value === "reference" || value === "spec" || value === "platform_docs" || value === "vendor_docs";
}
export function isLessonSourceVersionKind(value: unknown): value is LessonCitation["source_version_kind"] {
  return value === "fixed" || value === "rolling";
}
export function isSafeHttpUrl(value: unknown): value is string {
  if (!isString(value)) return false;
  try {
    const parsed = new URL(value);
    return (parsed.protocol === "http:" || parsed.protocol === "https:") && !parsed.username && !parsed.password;
  } catch {
    return false;
  }
}

export function toLearningLanguageCatalogItem(payload: unknown): LearningLanguageCatalogItem | null {
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

export function toLearningPlanSession(payload: unknown): LearningPlanSession | null {
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

export function toLearningPlanDraft(payload: unknown): LearningPlanDraft | null {
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

export function toLearningPlanProfile(payload: unknown): LearningPlanProfile | null {
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

export function toLearningPlanModule(payload: unknown): LearningPlanModule | null {
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

export function toLearningPlanNode(payload: unknown): LearningPlanNode | null {
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

export function isLearningTrackStatus(value: unknown): value is LearningTrackSummary["status"] {
  return value === "active" || value === "paused" || value === "completed" || value === "archived";
}

export function isExecutionTier(value: unknown): value is ExecutionTier {
  return value === "teaching_local" || value === "container_verified" || value === "static_only" || value === "unavailable";
}

export function isModelReviewAuthoringState(value: unknown): value is ModelReviewAuthoringRun["state"] {
  return value === "pending" || value === "claimed" || value === "running" || value === "validating" || value === "completed" || value === "failed" || value === "cancelled";
}

export function isVisibleEvidenceCheckType(value: unknown): value is ModelReviewVisibleEvidence["checks"][number]["check_type"] {
  return value === "parser" || value === "compile_or_typecheck" || value === "visible_tests" || value === "hidden_tests" || value === "coverage";
}

export function isModelReviewFindingStatus(value: unknown): value is ModelReviewFindingFeedback["status"] {
  return value === "supported" || value === "partial" || value === "unsupported" || value === "duplicate";
}

export function normalizedLineCount(value: string): number {
  const normalized = value.replace(/\r\n?/g, "\n");
  const lines = normalized.split("\n");
  return normalized.endsWith("\n") ? lines.length - 1 : lines.length;
}

export function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

export function isPositiveSafeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0;
}

export function isExerciseType(value: unknown): value is LessonGateExercise["exercise_type"] {
  return value === "code_completion" || value === "sql_query" || value === "browser_preview" || value === "static_code_reasoning" || value === "model_code_review";
}

export function isGateRequirementKind(value: unknown): value is "required" | "recommended" | "diagnostic" {
  return value === "required" || value === "recommended" || value === "diagnostic";
}

export function isExecutionRequirement(value: unknown): value is "required" | "optional" | "forbidden" {
  return value === "required" || value === "optional" || value === "forbidden";
}

export function isLessonGateState(value: unknown): value is "available" | "in_progress" | "passed" | "remediation_required" {
  return value === "available" || value === "in_progress" || value === "passed" || value === "remediation_required";
}

export function isLessonGateAction(value: unknown): value is LessonGateAction {
  return value === "prepare" || value === "hint" || value === "run" || value === "submit";
}

export function isExerciseAttemptType(value: unknown): value is ExerciseAttemptState["attempt_type"] {
  return value === "run" || value === "submit" || value === "diagnostic_submit";
}

export function isExerciseAttemptOutcome(value: unknown): value is ExerciseAttemptOutcome {
  return value === "passed" || value === "failed" || value === "timed_out" || value === "cancelled" || value === "unavailable" || value === "invalid";
}

export function isExerciseIndependence(value: unknown): value is ExerciseAttemptState["independence"] {
  return value === "independent" || value === "hinted" || value === "remediated";
}

export function isModelReviewAssistanceKind(value: unknown): value is ExerciseAttemptState["assistance_kind"] {
  return isExerciseIndependence(value) || value === "validation_evidence_viewed";
}

export function isModuleDiagnosticState(value: unknown): value is ModuleDiagnosticState["state"] {
  return value === "active" || value === "failed" || value === "passed_pending_confirmation" || value === "confirmed" || value === "expired";
}

export function isScore(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
}

export function toScoreRecord(value: unknown): Record<string, number> | null {
  if (!isRecord(value)) return null;
  const entries = Object.entries(value);
  if (entries.some(([key, score]) => key.length === 0 || !isScore(score))) return null;
  return Object.fromEntries(entries) as Record<string, number>;
}

export function isLearningProgressStatus(value: unknown): value is LearningRoadmapNode["progress_status"] {
  return value === "locked" || value === "available" || value === "in_progress" || value === "completed" ||
    value === "review_due" || value === "diagnostic_skipped";
}

export function isReviewRiskLevel(value: unknown): value is ReviewQueueItem["risk_level"] {
  return value === "low" || value === "normal" || value === "high" || value === "critical";
}

export function isReviewSessionState(value: unknown): value is ReviewSession["state"] {
  return value === "blocked" || value === "active" || value === "ready_to_finalize" ||
    value === "finalized" || value === "cancelled";
}

export function isReviewSessionStage(value: unknown): value is ReviewSession["stage"] {
  return value === "warmup" || value === "practice" || value === "final_summary";
}

export function isReviewRating(value: unknown): value is NonNullable<ReviewSession["finalization"]>["rating"] {
  return value === "again" || value === "hard" || value === "good" || value === "easy";
}

export function isSelectionTier(value: unknown): value is LearningLanguageCatalogItem["selection_tier"] {
  return value === "core" || value === "extended" || value === "degraded" || value === "unavailable";
}

export function isCapabilityState(value: unknown): value is LearningLanguageCatalogItem["lesson_generation_state"] {
  return value === "full" || value === "partial" || value === "planned" || value === "unsupported";
}

export function isSourceTrustPolicy(value: unknown): value is LearningLanguageCatalogItem["source_trust_policy"] {
  return value === "official" || value === "trusted_de_facto" || value === "internal";
}

export function isLearningPlanSessionStatus(value: unknown): value is LearningPlanSession["status"] {
  return value === "collecting" || value === "draft_ready" || value === "confirmed" || value === "cancelled";
}

export function isExperienceLevel(value: unknown): value is LearningPlanProfile["experience_level"] {
  return value === "new" || value === "beginner" || value === "intermediate" || value === "advanced";
}
