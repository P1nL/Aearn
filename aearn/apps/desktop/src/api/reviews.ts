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

import {
  isExecutionTier, isExerciseIndependence, isExerciseType, isModelReviewAssistanceKind, isPositiveSafeInteger, isReviewRating, isReviewRiskLevel, isReviewSessionStage, isReviewSessionState, isSha256, toLessonGateResult, toModelReviewArtifact, toModelReviewPrompt
} from "./learning";

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
