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
