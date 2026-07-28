import type {
  ApiError,
  ApiHealth,
  CodeCompletionResult,
  CreatedKnowledgePoint,
  CreatedModule,
  CreatedPlanResponse,
  DashboardResponse,
  EnvironmentComponent,
  EnvironmentComponentStatus,
  EnvironmentDoctorReport,
  EnvironmentGuidance,
  EnvironmentGuidanceSeverity,
  EnvironmentLanguageRunner,
  EnvironmentOverallStatus,
  EnvironmentProductStatus,
  ExplainErrorResponse,
  ExplanationFocus,
  ExplanationCheckResponse,
  HintLevel,
  HintResponse,
  HarnessCutoverDecision,
  KnowledgePointDocumentationResponse,
  Language,
  LanguageCourse,
  LocalUserDataSummary,
  LocalUserDeleteResponse,
  LocalUserExportPayload,
  LocalUserListResponse,
  LocalUserResetResponse,
  LearningExercise,
  LearningHistoryResponse,
  LearningMode,
  LearningSessionInitialToolCall,
  LearningSessionResponse,
  NoteListResponse,
  NoteRecord,
  PlanDraft,
  ReviewDueItem,
  ReviewHistoryMessage,
  ReviewAiPatchAnswer,
  ReviewExerciseResultResponse,
  ReviewMessagesResponse,
  ReviewSessionResponse,
  ReviewWarmupResultResponse,
  ReviewStateSummary,
  ResumeContextResponse,
  RunExerciseResponse,
  RuntimeProfile,
  RuntimeStatus,
  SubmitExerciseResponse,
  TestResult,
  TodayReviewsResponse,
  TriggerConceptCheckResponse,
  UserPreferencesUpdate,
  UserProfile,
  TutorActivityItem,
  TutorConversationResponse,
  TutorInboxItem,
  TutorInputAcceptedResponse,
  TutorMemoryItem,
  TutorPlanRevision,
  TutorPlanRevisionList,
  TutorPreferences,
  TutorRunState,
} from "./types";

import { ApiRequestError } from "./types";

export const API_BASE_URL = "http://127.0.0.1:8001";

export async function fetchApiHealth(signal?: AbortSignal): Promise<ApiHealth> {
  const payload = await requestJson(`${API_BASE_URL}/health`, { signal });
  if (!isApiHealth(payload)) {
    throw new Error("Health check returned an invalid payload");
  }
  return payload;
}

export async function fetchEnvironmentDoctor(signal?: AbortSignal): Promise<EnvironmentDoctorReport> {
  const payload = await requestJson(`${API_BASE_URL}/api/environment/doctor`, { signal });
  if (!isEnvironmentDoctorReport(payload)) {
    throw new Error("Environment doctor returned an invalid payload");
  }
  return payload;
}

export async function fetchLanguageCourses(signal?: AbortSignal): Promise<LanguageCourse[]> {
  const payload = await requestJson(`${API_BASE_URL}/api/language-courses`, { signal });
  if (!isRecord(payload) || !Array.isArray(payload.items)) {
    throw new Error("Course catalog returned an invalid payload");
  }
  return payload.items.filter(isLanguageCourse);
}

export async function createUser(displayName: string, signal?: AbortSignal): Promise<UserProfile> {
  const payload = await requestJson(`${API_BASE_URL}/api/users`, {
    method: "POST",
    body: JSON.stringify({
      display_name: displayName,
      learning_style: "practice_first",
      teaching_preference: "step_by_step",
      encouragement_preference: "direct",
    }),
    signal,
  });
  if (!isRecord(payload) || !isUserProfile(payload.user)) {
    throw new Error("User API returned an invalid payload");
  }
  return payload.user;
}

export async function fetchUserProfile(userId: string, signal?: AbortSignal): Promise<UserProfile> {
  const payload = await requestJson(`${API_BASE_URL}/api/users/${encodeURIComponent(userId)}`, { signal });
  if (!isRecord(payload) || !isUserProfile(payload.user)) {
    throw new Error("User profile API returned an invalid payload");
  }
  return payload.user;
}

export async function fetchLocalUsers(signal?: AbortSignal): Promise<LocalUserListResponse> {
  const payload = await requestJson(`${API_BASE_URL}/api/users`, { signal });
  if (!isLocalUserListResponse(payload)) {
    throw new Error("Local users API returned an invalid payload");
  }
  return payload;
}

export async function fetchUserDataSummary(userId: string, signal?: AbortSignal): Promise<LocalUserDataSummary> {
  const payload = await requestJson(`${API_BASE_URL}/api/users/${encodeURIComponent(userId)}/data-summary`, { signal });
  if (!isRecord(payload) || !isLocalUserDataSummary(payload.summary)) {
    throw new Error("User data summary API returned an invalid payload");
  }
  return payload.summary;
}

export async function fetchHarnessCutover(userId: string, signal?: AbortSignal): Promise<HarnessCutoverDecision> {
  const payload = await requestJson(
    `${API_BASE_URL}/api/harness/cutover?${new URLSearchParams({ user_id: userId }).toString()}`,
    { signal },
  );
  if (!isHarnessCutoverDecision(payload)) {
    throw new Error("Harness cutover API returned an invalid payload");
  }
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
    headers: { "Idempotency-Key": input.clientActionId },
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
  if (!isHarnessCutoverDecision(payload)) {
    throw new Error("Harness cutover confirmation returned an invalid payload");
  }
  return payload;
}

export async function exportLocalUserData(userId: string): Promise<LocalUserExportPayload> {
  const payload = await requestJson(`${API_BASE_URL}/api/users/${encodeURIComponent(userId)}/export`);
  if (!isLocalUserExportPayload(payload)) {
    throw new Error("User export API returned an invalid payload");
  }
  return payload;
}

export async function resetLocalUserData(userId: string): Promise<LocalUserResetResponse> {
  const payload = await requestJson(`${API_BASE_URL}/api/users/${encodeURIComponent(userId)}/reset-data`, {
    method: "POST",
    body: JSON.stringify({ confirm: true }),
  });
  if (!isLocalUserResetResponse(payload)) {
    throw new Error("User reset API returned an invalid payload");
  }
  return payload;
}

export async function deleteLocalUser(userId: string): Promise<LocalUserDeleteResponse> {
  const payload = await requestJson(`${API_BASE_URL}/api/users/${encodeURIComponent(userId)}`, {
    method: "DELETE",
    body: JSON.stringify({ confirm: true }),
  });
  if (!isLocalUserDeleteResponse(payload)) {
    throw new Error("User delete API returned an invalid payload");
  }
  return payload;
}

export async function updateUserPreferences(
  userId: string,
  input: UserPreferencesUpdate,
): Promise<UserProfile> {
  const payload = await requestJson(`${API_BASE_URL}/api/users/${encodeURIComponent(userId)}/preferences`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
  if (!isRecord(payload) || !isUserProfile(payload.user)) {
    throw new Error("User preferences API returned an invalid payload");
  }
  return payload.user;
}

export type GeneratePlanInput = {
  userId: string;
  mode: LearningMode;
  courseId: string;
  language: Language;
  goalText: string;
  materialTitle: string;
  materialContent: string;
};

export async function generatePlanDraft(input: GeneratePlanInput): Promise<PlanDraft> {
  const body =
    input.mode === "goal_based"
      ? {
          user_id: input.userId,
          mode: input.mode,
          goal_text: input.goalText,
          course_id: input.courseId,
          language: input.language,
          target_level: "beginner_to_intermediate",
        }
      : {
          user_id: input.userId,
          mode: input.mode,
          course_id: input.courseId,
          language: input.language,
          target_level: "beginner",
          materials: [
            {
              type: "text",
              title: input.materialTitle || "用户资料",
              content: input.materialContent,
            },
          ],
        };
  const payload = await requestJson(`${API_BASE_URL}/api/plans/generate`, {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!isRecord(payload) || !isPlanDraft(payload.plan_draft)) {
    throw new Error("Plan generation returned an invalid payload");
  }
  return payload.plan_draft;
}

export async function confirmPlan(userId: string, planDraft: PlanDraft): Promise<CreatedPlanResponse> {
  const payload = await requestJson(`${API_BASE_URL}/api/plans`, {
    method: "POST",
    body: JSON.stringify({
      user_id: userId,
      plan_draft: planDraft,
    }),
  });
  if (!isCreatedPlanResponse(payload)) {
    throw new Error("Plan confirmation returned an invalid payload");
  }
  return payload;
}

export async function confirmOnboardingPlan(
  conversationId: string,
  userId: string,
): Promise<CreatedPlanResponse> {
  const payload = await requestJson(
    `${API_BASE_URL}/api/onboarding/${encodeURIComponent(conversationId)}/confirm_plan`,
    {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    },
  );
  if (!isCreatedPlanResponse(payload)) {
    throw new Error("Onboarding plan confirmation returned an invalid payload");
  }
  return payload;
}

export async function fetchPlanDetail(planId: string, userId: string, signal?: AbortSignal): Promise<CreatedPlanResponse> {
  const query = new URLSearchParams({ user_id: userId });
  const payload = await requestJson(`${API_BASE_URL}/api/plans/${encodeURIComponent(planId)}?${query.toString()}`, { signal });
  if (!isCreatedPlanResponse(payload)) {
    throw new Error("Plan detail API returned an invalid payload");
  }
  return payload;
}

export async function fetchDashboard(userId: string, signal?: AbortSignal): Promise<DashboardResponse> {
  const payload = await requestJson(`${API_BASE_URL}/api/dashboard?user_id=${encodeURIComponent(userId)}`, {
    signal,
  });
  if (!isDashboardResponse(payload)) {
    throw new Error("Dashboard API returned an invalid payload");
  }
  return payload;
}

export async function fetchResumeContext(
  userId: string,
  planId: string,
  signal?: AbortSignal,
): Promise<ResumeContextResponse> {
  const payload = await requestJson(
    `${API_BASE_URL}/api/learning-sessions/resume?user_id=${encodeURIComponent(userId)}&plan_id=${encodeURIComponent(planId)}`,
    { signal },
  );
  if (!isResumeContextResponse(payload)) {
    throw new Error("Resume API returned an invalid payload");
  }
  return payload;
}

export async function startLearningSession(input: {
  userId: string;
  planId: string;
  knowledgePointId: string;
}): Promise<LearningSessionResponse> {
  const payload = await requestJson(`${API_BASE_URL}/api/learning-sessions/start`, {
    method: "POST",
    body: JSON.stringify({
      user_id: input.userId,
      plan_id: input.planId,
      knowledge_point_id: input.knowledgePointId,
    }),
  });
  if (!isLearningSessionResponse(payload)) {
    throw new Error("Learning session start returned an invalid payload");
  }
  return payload;
}

export async function fetchKnowledgePointDocumentation(input: {
  userId: string;
  knowledgePointId: string;
  signal?: AbortSignal;
}): Promise<KnowledgePointDocumentationResponse> {
  const query = new URLSearchParams({ user_id: input.userId });
  const payload = await requestJson(
    `${API_BASE_URL}/api/learning-sessions/knowledge-points/${encodeURIComponent(input.knowledgePointId)}/documentation?${query.toString()}`,
    { signal: input.signal },
  );
  if (!isKnowledgePointDocumentationResponse(payload)) {
    throw new Error("Knowledge point documentation API returned an invalid payload");
  }
  return payload;
}

export async function triggerConceptCheck(input: {
  userId: string;
  sessionId: string;
}): Promise<TriggerConceptCheckResponse> {
  const payload = await requestJson(
    `${API_BASE_URL}/api/learning-sessions/${encodeURIComponent(input.sessionId)}/trigger-concept-check`,
    {
      method: "POST",
      body: JSON.stringify({ user_id: input.userId }),
    },
  );
  if (!isTriggerConceptCheckResponse(payload)) {
    throw new Error("Concept check trigger API returned an invalid payload");
  }
  return payload;
}

export async function fetchLearningHistory(input: {
  userId: string;
  knowledgePointId: string;
  activeSessionId?: string | null;
  signal?: AbortSignal;
}): Promise<LearningHistoryResponse> {
  const query = new URLSearchParams({
    user_id: input.userId,
    knowledge_point_id: input.knowledgePointId,
  });
  if (input.activeSessionId) {
    query.set("active_session_id", input.activeSessionId);
  }
  const payload = await requestJson(`${API_BASE_URL}/api/learning-sessions/history?${query.toString()}`, {
    signal: input.signal,
  });
  if (!isLearningHistoryResponse(payload)) {
    throw new Error("Learning history API returned an invalid payload");
  }
  return payload;
}

export async function runLearningExercise(input: {
  userId: string;
  sessionId: string;
  exerciseId: string;
  code: string;
  filledBlanks: Record<string, string>;
  runtimeProfileId: string;
  runMode?: "preview" | "visible_tests";
}): Promise<RunExerciseResponse> {
  const payload = await requestJson(
    `${API_BASE_URL}/api/learning-sessions/${input.sessionId}/exercises/${input.exerciseId}/run`,
    {
      method: "POST",
      body: JSON.stringify({
        user_id: input.userId,
        code: input.code,
        filled_blanks: input.filledBlanks,
        runtime_profile_id: input.runtimeProfileId,
        run_mode: input.runMode ?? "visible_tests",
      }),
    },
  );
  if (!isRunExerciseResponse(payload)) {
    throw new Error("Run exercise returned an invalid payload");
  }
  return payload;
}

export async function submitLearningExercise(input: {
  userId: string;
  sessionId: string;
  exerciseId: string;
  attemptId: string;
  code: string;
  filledBlanks: Record<string, string>;
  submitVersion?: number;
  explanation?: string;
  hintUsageCount?: number;
  errorCount?: number;
}): Promise<SubmitExerciseResponse> {
  const payload = await requestJson(
    `${API_BASE_URL}/api/learning-sessions/${input.sessionId}/exercises/${input.exerciseId}/submit`,
    {
      method: "POST",
      body: JSON.stringify({
        user_id: input.userId,
        attempt_id: input.attemptId,
        code: input.code,
        filled_blanks: input.filledBlanks,
        submit_version: input.submitVersion ?? 1,
        explanation: input.explanation,
        hint_usage_count: input.hintUsageCount ?? 0,
        error_count: input.errorCount ?? 0,
      }),
    },
  );
  if (!isSubmitExerciseResponse(payload)) {
    throw new Error("Submit exercise returned an invalid payload");
  }
  return payload;
}

export async function requestLearningHint(input: {
  userId: string;
  sessionId: string;
  exerciseId: string;
  attemptId: string;
  currentCode: string;
  blankId: string;
  hintLevel: HintLevel;
}): Promise<HintResponse> {
  const payload = await requestJson(
    `${API_BASE_URL}/api/learning-sessions/${input.sessionId}/exercises/${input.exerciseId}/hint`,
    {
      method: "POST",
      body: JSON.stringify({
        user_id: input.userId,
        attempt_id: input.attemptId,
        current_code: input.currentCode,
        blank_id: input.blankId,
        hint_level: input.hintLevel,
      }),
    },
  );
  if (!isHintResponse(payload)) {
    throw new Error("Hint API returned an invalid payload");
  }
  return payload;
}

export async function explainLearningError(input: {
  userId: string;
  sessionId: string;
  attemptId: string;
  errorMessage: string | null;
  stderr: string;
  failedTests: Array<{ case_id: string; case_type: string; message: string }>;
  currentCode: string;
}): Promise<ExplainErrorResponse> {
  const payload = await requestJson(
    `${API_BASE_URL}/api/learning-sessions/${input.sessionId}/attempts/${input.attemptId}/explain-error`,
    {
      method: "POST",
      body: JSON.stringify({
        user_id: input.userId,
        error_message: input.errorMessage,
        stderr: input.stderr,
        failed_tests: input.failedTests,
        current_code: input.currentCode,
      }),
    },
  );
  if (!isExplainErrorResponse(payload)) {
    throw new Error("Explain-error API returned an invalid payload");
  }
  return payload;
}

export async function checkLearningExplanation(input: {
  userId: string;
  sessionId: string;
  attemptId: string;
  explanation: string;
  focus: ExplanationFocus;
  round: number;
}): Promise<ExplanationCheckResponse> {
  const payload = await requestJson(
    `${API_BASE_URL}/api/learning-sessions/${input.sessionId}/attempts/${input.attemptId}/check-explanation`,
    {
      method: "POST",
      body: JSON.stringify({
        user_id: input.userId,
        explanation: input.explanation,
        focus: input.focus,
        round: input.round,
      }),
    },
  );
  if (!isExplanationCheckResponse(payload)) {
    throw new Error("Explanation-check API returned an invalid payload");
  }
  return payload;
}

export async function fetchTodayReviews(userId: string, signal?: AbortSignal): Promise<TodayReviewsResponse> {
  const payload = await requestJson(`${API_BASE_URL}/api/reviews/today?user_id=${encodeURIComponent(userId)}`, {
    signal,
  });
  if (!isTodayReviewsResponse(payload)) {
    throw new Error("Today reviews API returned an invalid payload");
  }
  return payload;
}

export async function startReviewSession(input: {
  userId: string;
  knowledgePointId: string;
}): Promise<ReviewSessionResponse> {
  const payload = await requestJson(`${API_BASE_URL}/api/reviews/start`, {
    method: "POST",
    body: JSON.stringify({
      user_id: input.userId,
      knowledge_point_id: input.knowledgePointId,
    }),
  });
  if (!isReviewSessionResponse(payload)) {
    throw new Error("Review session start returned an invalid payload");
  }
  return payload;
}

export async function fetchReviewMessages(input: {
  userId: string;
  sessionId: string;
  signal?: AbortSignal;
}): Promise<ReviewMessagesResponse> {
  const query = new URLSearchParams({ user_id: input.userId });
  const payload = await requestJson(
    `${API_BASE_URL}/api/reviews/${encodeURIComponent(input.sessionId)}/messages?${query.toString()}`,
    { signal: input.signal },
  );
  if (!isReviewMessagesResponse(payload)) {
    throw new Error("Review messages API returned an invalid payload");
  }
  return payload;
}

export async function submitReviewWarmupResult(input: {
  userId: string;
  sessionId: string;
  action: "answer";
  answer?: string;
}): Promise<ReviewWarmupResultResponse> {
  const payload = await requestJson(`${API_BASE_URL}/api/reviews/${input.sessionId}/warmup-result`, {
    method: "POST",
    body: JSON.stringify({
      user_id: input.userId,
      action: input.action,
      answer: input.answer,
    }),
  });
  if (!isReviewWarmupResultResponse(payload)) {
    throw new Error("Review warmup result API returned an invalid payload");
  }
  return payload;
}

export async function submitReviewExerciseResult(input: {
  userId: string;
  sessionId: string;
  exerciseId: string;
  attemptId?: string;
  code: string;
  filledBlanks: Record<string, string>;
  explanation?: string;
  hintUsageCount?: number;
  errorCount?: number;
  reviewAiPatchAnswer?: ReviewAiPatchAnswer;
}): Promise<ReviewExerciseResultResponse> {
  const payload = await requestJson(`${API_BASE_URL}/api/reviews/${input.sessionId}/exercise-result`, {
    method: "POST",
    body: JSON.stringify({
      user_id: input.userId,
      exercise_id: input.exerciseId,
      attempt_id: input.attemptId,
      code: input.code,
      filled_blanks: input.filledBlanks,
      explanation: input.explanation,
      hint_usage_count: input.hintUsageCount ?? 0,
      error_count: input.errorCount ?? 0,
      review_ai_patch_answer: input.reviewAiPatchAnswer,
    }),
  });
  if (!isReviewExerciseResultResponse(payload)) {
    throw new Error("Review exercise result API returned an invalid payload");
  }
  return payload;
}

export async function fetchNotes(input: {
  userId: string;
  knowledgePointId?: string;
  limit?: number;
  signal?: AbortSignal;
}): Promise<NoteListResponse> {
  const query = new URLSearchParams({
    user_id: input.userId,
    limit: String(input.limit ?? 20),
  });
  if (input.knowledgePointId) {
    query.set("knowledge_point_id", input.knowledgePointId);
  }
  const payload = await requestJson(`${API_BASE_URL}/api/notes?${query.toString()}`, {
    signal: input.signal,
  });
  if (!isNoteListResponse(payload)) {
    throw new Error("Notes API returned an invalid payload");
  }
  return payload;
}

export async function createNote(input: {
  userId: string;
  knowledgePointId: string;
  title?: string;
  contentMarkdown?: string;
  source?: {
    sessionId?: string;
    attemptId?: string;
  };
}): Promise<NoteRecord> {
  const payload = await requestJson(`${API_BASE_URL}/api/notes`, {
    method: "POST",
    body: JSON.stringify({
      user_id: input.userId,
      knowledge_point_id: input.knowledgePointId,
      title: input.title,
      content_markdown: input.contentMarkdown ?? "",
      source: input.source
        ? {
            session_id: input.source.sessionId,
            attempt_id: input.source.attemptId,
          }
        : undefined,
    }),
  });
  if (!isRecord(payload) || !isNoteRecord(payload.note)) {
    throw new Error("Create note API returned an invalid payload");
  }
  return payload.note;
}

export async function updateNote(input: {
  noteId: string;
  userId: string;
  title?: string;
  contentMarkdown?: string;
  isUserEdited?: boolean;
}): Promise<NoteRecord> {
  const payload = await requestJson(`${API_BASE_URL}/api/notes/${input.noteId}`, {
    method: "PATCH",
    body: JSON.stringify({
      user_id: input.userId,
      title: input.title,
      content_markdown: input.contentMarkdown,
      is_user_edited: input.isUserEdited ?? true,
    }),
  });
  if (!isRecord(payload) || !isNoteRecord(payload.note)) {
    throw new Error("Update note API returned an invalid payload");
  }
  return payload.note;
}

export async function requestNoteAgentDraft(input: {
  noteId: string;
  userId: string;
  style?: string;
  focus?: string;
  source?: {
    sessionId?: string;
    attemptId?: string;
  };
}): Promise<NoteRecord> {
  const payload = await requestJson(`${API_BASE_URL}/api/notes/${input.noteId}/agent-draft`, {
    method: "POST",
    body: JSON.stringify({
      user_id: input.userId,
      style: input.style ?? "concise",
      focus: input.focus ?? "mistake_summary",
      source: input.source
        ? {
            session_id: input.source.sessionId,
            attempt_id: input.source.attemptId,
          }
        : undefined,
    }),
  });
  if (!isRecord(payload) || !isNoteRecord(payload.note)) {
    throw new Error("Note agent-draft API returned an invalid payload");
  }
  return payload.note;
}

export async function createTutorConversation(input: {
  userId: string;
  clientActionId: string;
  conversationId?: string;
}): Promise<TutorConversationResponse> {
  const payload = await requestJson(`${API_BASE_URL}/api/tutor/conversations`, {
    method: "POST",
    headers: tutorMutationHeaders(input.clientActionId),
    body: JSON.stringify({
      user_id: input.userId,
      client_action_id: input.clientActionId,
      ...(input.conversationId ? { conversation_id: input.conversationId } : {}),
    }),
  });
  const response = toTutorConversationResponse(payload);
  if (!response) throw new Error("Tutor conversation API returned an invalid payload");
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
      body: JSON.stringify({
        user_id: input.userId,
        content: input.content,
        client_action_id: input.clientActionId,
      }),
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
    body: JSON.stringify({
      user_id: input.userId,
      content: input.content,
      client_action_id: input.clientActionId,
    }),
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
  const payload: unknown = await response.json();
  if (!response.ok) {
    if (isApiErrorEnvelope(payload)) {
      throw new ApiRequestError(payload.error);
    }
    throw new Error(`API request failed with status ${response.status}`);
  }
  return payload;
}

function isApiHealth(payload: unknown): payload is ApiHealth {
  return isRecord(payload) && payload.status === "ok" && typeof payload.service === "string";
}

function isEnvironmentDoctorReport(payload: unknown): payload is EnvironmentDoctorReport {
  return (
    isRecord(payload) &&
    typeof payload.generated_at === "string" &&
    isRecord(payload.platform) &&
    typeof payload.platform.system === "string" &&
    typeof payload.platform.release === "string" &&
    typeof payload.platform.python_executable === "string" &&
    isRecord(payload.summary) &&
    isEnvironmentOverallStatus(payload.summary.overall_status) &&
    typeof payload.summary.ready_count === "number" &&
    typeof payload.summary.missing_required_count === "number" &&
    typeof payload.summary.planned_runner_count === "number" &&
    Array.isArray(payload.components) &&
    payload.components.every(isEnvironmentComponent) &&
    Array.isArray(payload.language_runners) &&
    payload.language_runners.every(isEnvironmentLanguageRunner) &&
    Array.isArray(payload.guidance) &&
    payload.guidance.every(isEnvironmentGuidance)
  );
}

function isEnvironmentComponent(payload: unknown): payload is EnvironmentComponent {
  return (
    isRecord(payload) &&
    typeof payload.component_id === "string" &&
    typeof payload.label === "string" &&
    typeof payload.kind === "string" &&
    isEnvironmentComponentStatus(payload.status) &&
    (typeof payload.version === "string" || payload.version === null) &&
    (typeof payload.executable_path === "string" || payload.executable_path === null) &&
    Array.isArray(payload.required_for) &&
    payload.required_for.every((item) => typeof item === "string") &&
    (typeof payload.guidance_id === "string" || payload.guidance_id === null) &&
    typeof payload.message === "string" &&
    isRecord(payload.diagnostic) &&
    (typeof payload.diagnostic.command === "string" || payload.diagnostic.command === null) &&
    Array.isArray(payload.diagnostic.args) &&
    payload.diagnostic.args.every((item) => typeof item === "string") &&
    (typeof payload.diagnostic.exit_code === "number" || payload.diagnostic.exit_code === null) &&
    typeof payload.diagnostic.stdout === "string" &&
    typeof payload.diagnostic.stderr === "string"
  );
}

function isEnvironmentLanguageRunner(payload: unknown): payload is EnvironmentLanguageRunner {
  return (
    isRecord(payload) &&
    typeof payload.language_id === "string" &&
    typeof payload.display_name === "string" &&
    typeof payload.runner_key === "string" &&
    typeof payload.execution === "string" &&
    typeof payload.capability_state === "string" &&
    typeof payload.supports_execution === "boolean" &&
    isEnvironmentComponentStatus(payload.toolchain_status) &&
    isEnvironmentProductStatus(payload.product_status) &&
    (typeof payload.guidance_id === "string" || payload.guidance_id === null) &&
    typeof payload.disclosure === "string"
  );
}

function isEnvironmentGuidance(payload: unknown): payload is EnvironmentGuidance {
  return (
    isRecord(payload) &&
    typeof payload.guidance_id === "string" &&
    typeof payload.title === "string" &&
    Array.isArray(payload.applies_to) &&
    payload.applies_to.every((item) => typeof item === "string") &&
    isEnvironmentGuidanceSeverity(payload.severity) &&
    typeof payload.summary === "string" &&
    Array.isArray(payload.windows_steps) &&
    payload.windows_steps.every((item) => typeof item === "string") &&
    Array.isArray(payload.verification_commands) &&
    payload.verification_commands.every((item) => typeof item === "string") &&
    Array.isArray(payload.safety_notes) &&
    payload.safety_notes.every((item) => typeof item === "string") &&
    payload.source === "static_template"
  );
}

function isEnvironmentComponentStatus(payload: unknown): payload is EnvironmentComponentStatus {
  return payload === "ready" || payload === "missing" || payload === "error" || payload === "planned";
}

function isEnvironmentOverallStatus(payload: unknown): payload is EnvironmentOverallStatus {
  return payload === "ready" || payload === "needs_attention" || payload === "blocked";
}

function isEnvironmentProductStatus(payload: unknown): payload is EnvironmentProductStatus {
  return payload === "executable" || payload === "planned" || payload === "static_review" || payload === "unsupported";
}

function isEnvironmentGuidanceSeverity(payload: unknown): payload is EnvironmentGuidanceSeverity {
  return payload === "required" || payload === "recommended" || payload === "optional";
}

function isLanguageCourse(payload: unknown): payload is LanguageCourse {
  return (
    isRecord(payload) &&
    typeof payload.id === "string" &&
    typeof payload.title === "string" &&
    typeof payload.language === "string" &&
    isRuntimeProfile(payload.runtime_profile)
  );
}

function isUserProfile(payload: unknown): payload is UserProfile {
  return isRecord(payload) && typeof payload.id === "string" && typeof payload.display_name === "string";
}

function isLocalUserListResponse(payload: unknown): payload is LocalUserListResponse {
  return (
    isRecord(payload) &&
    Array.isArray(payload.items) &&
    payload.items.every(isLocalUserListItem) &&
    isRecord(payload.page_info) &&
    typeof payload.page_info.limit === "number" &&
    typeof payload.page_info.has_more === "boolean"
  );
}

function isLocalUserListItem(payload: unknown): boolean {
  if (!isRecord(payload)) {
    return false;
  }
  return (
    typeof payload.id === "string" &&
    typeof payload.display_name === "string" &&
    (typeof payload.learning_style === "string" || payload.learning_style === null) &&
    (typeof payload.teaching_preference === "string" || payload.teaching_preference === null) &&
    (typeof payload.encouragement_preference === "string" || payload.encouragement_preference === null) &&
    (typeof payload.profession === "string" || payload.profession === null) &&
    (typeof payload.background_context === "string" || payload.background_context === null) &&
    Array.isArray(payload.preferred_time_slots) &&
    isRecord(payload.reminder_preference) &&
    typeof payload.created_at === "string" &&
    typeof payload.updated_at === "string" &&
    typeof payload.plan_count === "number" &&
    (typeof payload.active_plan_id === "string" || payload.active_plan_id === null) &&
    (typeof payload.active_goal === "string" || payload.active_goal === null) &&
    (typeof payload.last_activity_at === "string" || payload.last_activity_at === null)
  );
}

function isLocalUserDataSummary(payload: unknown): payload is LocalUserDataSummary {
  return (
    isRecord(payload) &&
    isRecord(payload.user) &&
    typeof payload.user.id === "string" &&
    typeof payload.user.display_name === "string" &&
    isRecord(payload.counts) &&
    typeof payload.counts.active_plans === "number" &&
    typeof payload.counts.learning_sessions === "number" &&
    typeof payload.counts.attempts === "number" &&
    typeof payload.counts.notes === "number" &&
    (typeof payload.last_activity_at === "string" || payload.last_activity_at === null)
  );
}

function isHarnessCutoverDecision(payload: unknown): payload is HarnessCutoverDecision {
  if (!isRecord(payload) || typeof payload.cutover_version !== "string" || typeof payload.rollout_active !== "boolean") {
    return false;
  }
  if (!isHarnessCutoverState(payload.state) || !isHarnessCutoverNextAction(payload.next_action)) {
    return false;
  }
  if (payload.summary !== undefined && !isHarnessCutoverSummary(payload.summary)) {
    return false;
  }
  if (payload.summary_version !== undefined && typeof payload.summary_version !== "number") {
    return false;
  }
  if (payload.preview_nonce !== undefined && typeof payload.preview_nonce !== "string") {
    return false;
  }
  if (payload.summary_hash !== undefined && typeof payload.summary_hash !== "string") {
    return false;
  }
  if (payload.code !== undefined && typeof payload.code !== "string") {
    return false;
  }
  return true;
}

function isHarnessCutoverSummary(payload: unknown): boolean {
  if (!isRecord(payload) || !Array.isArray(payload.legacy_categories) || !Array.isArray(payload.legacy_profile_fields)) {
    return false;
  }
  if (!payload.legacy_categories.every((item) => isRecord(item) && typeof item.id === "string" && typeof item.count === "number")) {
    return false;
  }
  if (!payload.legacy_profile_fields.every((item) => isRecord(item) && typeof item.id === "string" && item.will_clear === true)) {
    return false;
  }
  return (
    isRecord(payload.checkpoint) &&
    (payload.checkpoint.state === "not_configured" || payload.checkpoint.state === "scoped" || payload.checkpoint.state === "unresolved") &&
    typeof payload.checkpoint.record_count === "number" &&
    Array.isArray(payload.retained_categories) &&
    payload.retained_categories.every((item) => typeof item === "string") &&
    typeof payload.target_state_present === "boolean"
  );
}

function isHarnessCutoverState(payload: unknown): payload is HarnessCutoverDecision["state"] {
  return payload === "rollout_inactive" || payload === "summary_ready" || payload === "verified"
    || payload === "blocked_target_state" || payload === "blocked_checkpoint_scope";
}

function isHarnessCutoverNextAction(payload: unknown): payload is HarnessCutoverDecision["next_action"] {
  return payload === "continue_legacy" || payload === "confirm_cutover" || payload === "enter_tutor"
    || payload === "resolve_cutover_block";
}

function isLocalUserResetResponse(payload: unknown): payload is LocalUserResetResponse {
  return (
    isRecord(payload) &&
    isUserProfile(payload.user) &&
    isLocalUserDataSummary(payload.before_summary) &&
    isLocalUserDataSummary(payload.summary) &&
    payload.next_action === "return_to_onboarding"
  );
}

function isLocalUserDeleteResponse(payload: unknown): payload is LocalUserDeleteResponse {
  return (
    isRecord(payload) &&
    typeof payload.deleted_user_id === "string" &&
    isLocalUserDataSummary(payload.before_summary) &&
    payload.next_action === "select_local_profile"
  );
}

function isLocalUserExportPayload(payload: unknown): payload is LocalUserExportPayload {
  return (
    isRecord(payload) &&
    typeof payload.export_version === "string" &&
    typeof payload.exported_at === "string" &&
    isRecord(payload.user) &&
    isLocalUserDataSummary(payload.summary) &&
    Array.isArray(payload.plans) &&
    Array.isArray(payload.notes) &&
    isRecord(payload.redaction)
  );
}

function isPlanDraft(payload: unknown): payload is PlanDraft {
  return (
    isRecord(payload) &&
    typeof payload.draft_id === "string" &&
    typeof payload.user_id === "string" &&
    Array.isArray(payload.modules) &&
    isRecord(payload.runtime_boundary)
  );
}

function isCreatedPlanResponse(payload: unknown): payload is CreatedPlanResponse {
  return (
    isRecord(payload) &&
    isRecord(payload.LearningPlan) &&
    typeof payload.LearningPlan.id === "string" &&
    typeof payload.LearningPlan.user_id === "string" &&
    typeof payload.LearningPlan.language_course_id === "string" &&
    typeof payload.LearningPlan.goal_text === "string" &&
    typeof payload.LearningPlan.language === "string" &&
    typeof payload.LearningPlan.target_level === "string" &&
    typeof payload.LearningPlan.mode === "string" &&
    (typeof payload.LearningPlan.deadline === "string" || payload.LearningPlan.deadline === null) &&
    typeof payload.LearningPlan.status === "string" &&
    typeof payload.LearningPlan.overall_progress === "number" &&
    (typeof payload.LearningPlan.current_module_id === "string" || payload.LearningPlan.current_module_id === null) &&
    Array.isArray(payload.modules) &&
    payload.modules.every(isCreatedModule) &&
    Array.isArray(payload.knowledge_points) &&
    payload.knowledge_points.every(isCreatedKnowledgePoint) &&
    isRecord(payload.next_entry_point) &&
    payload.next_entry_point.type === "learning_session" &&
    typeof payload.next_entry_point.plan_id === "string" &&
    (typeof payload.next_entry_point.knowledge_point_id === "string" ||
      payload.next_entry_point.knowledge_point_id === null)
  );
}

function isCreatedModule(payload: unknown): payload is CreatedModule {
  return (
    isRecord(payload) &&
    typeof payload.id === "string" &&
    typeof payload.plan_id === "string" &&
    typeof payload.title === "string" &&
    (typeof payload.description === "string" || payload.description === null) &&
    typeof payload.order_index === "number" &&
    typeof payload.status === "string" &&
    typeof payload.is_skippable === "boolean" &&
    typeof payload.is_adjustable === "boolean" &&
    typeof payload.estimated_sessions === "number"
  );
}

function isCreatedKnowledgePoint(payload: unknown): payload is CreatedKnowledgePoint {
  return (
    isRecord(payload) &&
    typeof payload.id === "string" &&
    typeof payload.module_id === "string" &&
    typeof payload.language_course_id === "string" &&
    typeof payload.title === "string" &&
    (typeof payload.description === "string" || payload.description === null) &&
    typeof payload.order_index === "number" &&
    Array.isArray(payload.skill_tags_json) &&
    payload.skill_tags_json.every((tag) => typeof tag === "string") &&
    typeof payload.status === "string" &&
    typeof payload.mastery_score === "number" &&
    (payload.review_state === undefined || isCreatedKnowledgePointReviewStatePreview(payload.review_state))
  );
}

function isCreatedKnowledgePointReviewStatePreview(
  payload: unknown,
): payload is CreatedKnowledgePoint["review_state"] {
  return (
    isRecord(payload) &&
    (typeof payload.due_at === "string" || payload.due_at === null) &&
    typeof payload.is_due === "boolean" &&
    typeof payload.label === "string"
  );
}

function isDashboardResponse(payload: unknown): payload is DashboardResponse {
  return (
    isRecord(payload) &&
    typeof payload.active_goal === "string" &&
    (typeof payload.current_stage === "string" || payload.current_stage === null) &&
    typeof payload.current_language === "string" &&
    isRecord(payload.current_course) &&
    typeof payload.current_course.id === "string" &&
    typeof payload.current_course.title === "string" &&
    Array.isArray(payload.today_learning_tasks) &&
    payload.today_learning_tasks.every(
      (item) =>
        isRecord(item) &&
        item.type === "learning_session" &&
        typeof item.plan_id === "string" &&
        (typeof item.knowledge_point_id === "string" || item.knowledge_point_id === null) &&
        typeof item.title === "string",
    ) &&
    typeof payload.today_review_count === "number" &&
    typeof payload.overall_progress === "number" &&
    typeof payload.resume_available === "boolean" &&
    isDashboardEntryPoint(payload.next_entry_point)
  );
}

function isDashboardEntryPoint(payload: unknown): payload is DashboardResponse["next_entry_point"] {
  return (
    isRecord(payload) &&
    typeof payload.type === "string" &&
    typeof payload.plan_id === "string" &&
    typeof payload.next_action === "string" &&
    ((payload.type === "resume" && payload.knowledge_point_id === undefined) ||
      ((payload.type === "learning_session" || payload.type === "review") &&
        (typeof payload.knowledge_point_id === "string" || payload.knowledge_point_id === null)))
  );
}

function isResumeContextResponse(payload: unknown): payload is ResumeContextResponse {
  return (
    isRecord(payload) &&
    (typeof payload.last_session_summary === "string" || payload.last_session_summary === null) &&
    isRecord(payload.next_entry_point) &&
    payload.next_entry_point.type === "learning_session" &&
    typeof payload.next_entry_point.plan_id === "string" &&
    (typeof payload.next_entry_point.knowledge_point_id === "string" || payload.next_entry_point.knowledge_point_id === null) &&
    typeof payload.next_entry_point.next_action === "string" &&
    (payload.current_module === null ||
      (isRecord(payload.current_module) &&
        typeof payload.current_module.id === "string" &&
        typeof payload.current_module.title === "string")) &&
    (typeof payload.current_stage === "string" || payload.current_stage === null) &&
    typeof payload.today_review_count === "number" &&
    typeof payload.resume_available === "boolean"
  );
}

function isLearningSessionResponse(payload: unknown): payload is LearningSessionResponse {
  return (
    isRecord(payload) &&
    typeof payload.session_id === "string" &&
    payload.session_type === "learn" &&
    isRecord(payload.context_snapshot) &&
    isRecord(payload.context_snapshot.KnowledgePoint) &&
    typeof payload.context_snapshot.KnowledgePoint.id === "string" &&
    isRuntimeProfile(payload.context_snapshot.RuntimeProfile) &&
    (payload.exercise === null || isLearningExercise(payload.exercise)) &&
    typeof payload.learning_stage === "string" &&
    isRecord(payload.learning_stage_state) &&
    Array.isArray(payload.lesson_outline) &&
    Array.isArray(payload.lesson_sources) &&
    typeof payload.initial_agent_message === "string" &&
    (!("latest_run" in payload) || payload.latest_run === null || isRunExerciseResponse(payload.latest_run)) &&
    (!("latest_submit" in payload) || payload.latest_submit === null || isSubmitExerciseResponse(payload.latest_submit)) &&
    (!("latest_workbench_state" in payload) ||
      payload.latest_workbench_state === null ||
      isLearningWorkbenchState(payload.latest_workbench_state))
  );
}

function isLearningWorkbenchState(payload: unknown): payload is LearningSessionResponse["latest_workbench_state"] {
  return (
    isRecord(payload) &&
    typeof payload.exercise_id === "string" &&
    typeof payload.source_attempt_id === "string" &&
    (payload.source_attempt_type === "run" || payload.source_attempt_type === "submit") &&
    typeof payload.code === "string" &&
    isStringRecord(payload.filled_blanks) &&
    (payload.run_mode === "preview" || payload.run_mode === "visible_tests" || payload.run_mode === null)
  );
}

function isKnowledgePointDocumentationResponse(payload: unknown): payload is KnowledgePointDocumentationResponse {
  return (
    isRecord(payload) &&
    typeof payload.knowledge_point_id === "string" &&
    typeof payload.title === "string" &&
    typeof payload.summary === "string" &&
    Array.isArray(payload.sections) &&
    payload.sections.every(isDocumentationSection) &&
    Array.isArray(payload.references) &&
    payload.references.every(
      (reference) =>
        isRecord(reference) &&
        typeof reference.title === "string" &&
        typeof reference.url === "string" &&
        (!("source_type" in reference) || reference.source_type === null || typeof reference.source_type === "string") &&
        (!("retrieved_at" in reference) || reference.retrieved_at === null || typeof reference.retrieved_at === "string"),
    ) &&
    typeof payload.generated_at === "string" &&
    typeof payload.cache_hit === "boolean"
  );
}

function isDocumentationSection(payload: unknown): payload is KnowledgePointDocumentationResponse["sections"][number] {
  return (
    isRecord(payload) &&
    typeof payload.id === "string" &&
    typeof payload.type === "string" &&
    typeof payload.title === "string" &&
    typeof payload.content_markdown === "string" &&
    Array.isArray(payload.code_blocks) &&
    payload.code_blocks.every(
      (block) =>
        isRecord(block) &&
        typeof block.language === "string" &&
        typeof block.code === "string" &&
        typeof block.caption === "string" &&
        (!("source_type" in block) || block.source_type === null || typeof block.source_type === "string"),
    )
  );
}

function isTriggerConceptCheckResponse(payload: unknown): payload is TriggerConceptCheckResponse {
  return (
    isRecord(payload) &&
    typeof payload.session_id === "string" &&
    payload.learning_stage === "concept_check" &&
    isRecord(payload.learning_stage_state) &&
    typeof payload.agent_message === "string" &&
    isRecord(payload.tool_call) &&
    typeof payload.tool_call.id === "string" &&
    payload.tool_call.name === "show_concept_intro" &&
    payload.tool_call.args !== undefined &&
    typeof payload.tool_call.status === "string"
  );
}

function isLearningHistoryResponse(payload: unknown): payload is LearningHistoryResponse {
  return (
    isRecord(payload) &&
    typeof payload.knowledge_point_id === "string" &&
    typeof payload.knowledge_point_title === "string" &&
    Array.isArray(payload.sessions) &&
    payload.sessions.every(
      (session) =>
        isRecord(session) &&
        typeof session.session_id === "string" &&
        typeof session.is_active === "boolean" &&
        Array.isArray(session.messages) &&
        session.messages.every(
          (message) =>
            isRecord(message) &&
            typeof message.id === "string" &&
            (message.role === "user" || message.role === "agent") &&
            typeof message.content === "string" &&
            (!("tool_calls" in message) ||
              (Array.isArray(message.tool_calls) && message.tool_calls.every(isLearningHistoryToolCall))),
        ),
    )
  );
}

function isLearningHistoryToolCall(payload: unknown): payload is LearningSessionInitialToolCall {
  return (
    isRecord(payload) &&
    typeof payload.id === "string" &&
    typeof payload.name === "string" &&
    payload.args !== undefined &&
    (payload.status === "pending" || payload.status === "running" || payload.status === "done" || payload.status === "error")
  );
}

function isRunExerciseResponse(payload: unknown): payload is RunExerciseResponse {
  return (
    isRecord(payload) &&
    typeof payload.attempt_id === "string" &&
    payload.attempt_type === "run" &&
    isRuntimeStatus(payload.runtime_status) &&
    typeof payload.stdout === "string" &&
    typeof payload.stderr === "string" &&
    typeof payload.test_pass_rate === "number" &&
    Array.isArray(payload.test_results) &&
    payload.test_results.every(isTestResult) &&
    typeof payload.next_action === "string"
  );
}

function isSubmitExerciseResponse(payload: unknown): payload is SubmitExerciseResponse {
  return (
    isRecord(payload) &&
    typeof payload.attempt_id === "string" &&
    isCodeCompletionResult(payload.code_completion_result) &&
    isRecord(payload.KnowledgePoint) &&
    typeof payload.KnowledgePoint.id === "string" &&
    isReviewStateSummary(payload.ReviewState) &&
    typeof payload.next_action === "string"
  );
}

function isHintResponse(payload: unknown): payload is HintResponse {
  return (
    isRecord(payload) &&
    isRecord(payload.hint) &&
    typeof payload.hint.hint_level === "string" &&
    typeof payload.hint.content === "string" &&
    typeof payload.hint_usage_count === "number" &&
    isRecord(payload.affected_score) &&
    typeof payload.affected_score.max_result === "string" &&
    typeof payload.affected_score.score_penalty_hint === "number" &&
    typeof payload.next_action === "string"
  );
}

function isExplainErrorResponse(payload: unknown): payload is ExplainErrorResponse {
  return (
    isRecord(payload) &&
    typeof payload.error_cause === "string" &&
    typeof payload.explanation === "string" &&
    typeof payload.fix_suggestion === "string" &&
    Array.isArray(payload.related_knowledge_points) &&
    payload.related_knowledge_points.every(
      (item) => isRecord(item) && typeof item.id === "string" && typeof item.title === "string",
    ) &&
    typeof payload.next_action === "string" &&
    (payload.generation_source === undefined ||
      payload.generation_source === "llm" ||
      payload.generation_source === "deterministic") &&
    (payload.generation_model === undefined || typeof payload.generation_model === "string")
  );
}

function isExplanationCheckResponse(payload: unknown): payload is ExplanationCheckResponse {
  return (
    isRecord(payload) &&
    typeof payload.result === "string" &&
    typeof payload.score === "number" &&
    isRecord(payload.score_breakdown) &&
    typeof payload.score_breakdown.explanation_check === "number" &&
    typeof payload.follow_up_required === "boolean" &&
    typeof payload.feedback === "string" &&
    typeof payload.next_action === "string"
  );
}

function isTodayReviewsResponse(payload: unknown): payload is TodayReviewsResponse {
  return (
    isRecord(payload) &&
    Array.isArray(payload.items) &&
    payload.items.every(isReviewDueItem) &&
    isRecord(payload.page_info) &&
    typeof payload.page_info.limit === "number" &&
    typeof payload.page_info.has_more === "boolean" &&
    typeof payload.timezone === "string" &&
    typeof payload.generated_at === "string"
  );
}

function isReviewDueItem(payload: unknown): payload is ReviewDueItem {
  return (
    isRecord(payload) &&
    isReviewStateSummary(payload.ReviewState) &&
    isRecord(payload.KnowledgePoint) &&
    typeof payload.KnowledgePoint.id === "string" &&
    typeof payload.KnowledgePoint.title === "string" &&
    Array.isArray(payload.KnowledgePoint.weak_points_json) &&
    isForgetRisk(payload.forget_risk)
  );
}

function isReviewSessionResponse(payload: unknown): payload is ReviewSessionResponse {
  return (
    isRecord(payload) &&
    typeof payload.session_id === "string" &&
    payload.session_type === "review" &&
    isRecord(payload.knowledge_point) &&
    typeof payload.knowledge_point.id === "string" &&
    typeof payload.knowledge_point.title === "string" &&
    Array.isArray(payload.knowledge_point.weak_points_json) &&
    isLearningExercise(payload.review_exercise) &&
    isReviewStateSummary(payload.ReviewState) &&
    typeof payload.review_stage === "string" &&
    isRecord(payload.current_node) &&
    isReviewWarmupState(payload.warmup) &&
    isRecord(payload.review_stage_state) &&
    typeof payload.variant_reason === "string" &&
    typeof payload.initial_agent_message === "string"
  );
}

function isReviewWarmupResultResponse(payload: unknown): payload is ReviewWarmupResultResponse {
  return (
    isRecord(payload) &&
    typeof payload.session_id === "string" &&
    typeof payload.review_stage === "string" &&
    isReviewWarmupState(payload.warmup) &&
    isRecord(payload.review_stage_state) &&
    isRecord(payload.current_node) &&
    (payload.next_action === "start_variant" || payload.next_action === "start_exercise" || payload.next_action === "retry_same")
  );
}

function isReviewMessagesResponse(payload: unknown): payload is ReviewMessagesResponse {
  return (
    isRecord(payload) &&
    typeof payload.session_id === "string" &&
    Array.isArray(payload.messages) &&
    payload.messages.every(isReviewHistoryMessage)
  );
}

function isReviewHistoryMessage(payload: unknown): payload is ReviewHistoryMessage {
  return (
    isRecord(payload) &&
    typeof payload.id === "string" &&
    (payload.role === "user" || payload.role === "agent") &&
    typeof payload.content === "string" &&
    (typeof payload.client_message_id === "string" || payload.client_message_id === null) &&
    (typeof payload.created_at === "string" || payload.created_at === null)
  );
}

function isReviewWarmupState(payload: unknown): payload is ReviewWarmupResultResponse["warmup"] {
  return (
    isRecord(payload) &&
    typeof payload.question === "string" &&
    typeof payload.expected_focus === "string" &&
    typeof payload.result === "string" &&
    typeof payload.repair_count === "number" &&
    typeof payload.off_topic_count === "number" &&
    (typeof payload.last_answer === "string" || payload.last_answer === null) &&
    (typeof payload.feedback === "string" || payload.feedback === null)
  );
}

function isReviewExerciseResultResponse(payload: unknown): payload is ReviewExerciseResultResponse {
  if (
    !isRecord(payload) ||
    typeof payload.result !== "string" ||
    typeof payload.score !== "number" ||
    !isRecord(payload.score_breakdown) ||
    typeof payload.fsrs_rating !== "string" ||
    !Array.isArray(payload.weak_points) ||
    typeof payload.feedback !== "string" ||
    !isCodeCompletionResult(payload.code_completion_result) ||
    typeof payload.next_action !== "string"
  ) {
    return false;
  }

  if (payload.next_action === "next_exercise") {
    return (
      typeof payload.attempt_id === "string" &&
      isLearningExercise(payload.review_exercise) &&
      typeof payload.review_stage === "string" &&
      isRecord(payload.review_stage_state) &&
      isRecord(payload.current_node) &&
      payload.final_result === null &&
      (payload.due_at === undefined || payload.due_at === null) &&
      (payload.forget_risk === undefined || isForgetRisk(payload.forget_risk)) &&
      (payload.ReviewState === undefined || isReviewStateSummary(payload.ReviewState)) &&
      (payload.KnowledgePoint === undefined ||
        (isRecord(payload.KnowledgePoint) && typeof payload.KnowledgePoint.id === "string"))
    );
  }

  if (payload.next_action === "schedule_review") {
    return (
      typeof payload.attempt_id === "string" &&
      (payload.review_stage === undefined || typeof payload.review_stage === "string") &&
      (payload.review_stage_state === undefined || isRecord(payload.review_stage_state)) &&
      (payload.current_node === undefined || isRecord(payload.current_node)) &&
      (payload.review_exercise === undefined || isLearningExercise(payload.review_exercise)) &&
      (payload.final_result === undefined ||
        (isRecord(payload.final_result) &&
          (typeof payload.final_result.final_fsrs_rating === "string") &&
          (typeof payload.final_result.due_at === "string" || payload.final_result.due_at === null) &&
          isForgetRisk(payload.final_result.forget_risk))) &&
      (typeof payload.due_at === "string" || payload.due_at === null) &&
      isForgetRisk(payload.forget_risk) &&
      isReviewStateSummary(payload.ReviewState) &&
      isRecord(payload.KnowledgePoint) &&
      typeof payload.KnowledgePoint.id === "string"
    );
  }

  if (payload.next_action === "retry_same") {
    return (
      typeof payload.review_stage === "string" &&
      isRecord(payload.review_stage_state) &&
      isRecord(payload.current_node) &&
      isLearningExercise(payload.review_exercise) &&
      typeof payload.judgement_ready === "boolean" &&
      (payload.judgement_blocking_fields === undefined || Array.isArray(payload.judgement_blocking_fields)) &&
      (payload.clarification_question === undefined || typeof payload.clarification_question === "string")
    );
  }

  return false;
}

function isNoteListResponse(payload: unknown): payload is NoteListResponse {
  return (
    isRecord(payload) &&
    Array.isArray(payload.items) &&
    payload.items.every(isNoteRecord) &&
    isRecord(payload.page_info) &&
    typeof payload.page_info.limit === "number" &&
    typeof payload.page_info.has_more === "boolean"
  );
}

function isNoteRecord(payload: unknown): payload is NoteRecord {
  return (
    isRecord(payload) &&
    typeof payload.id === "string" &&
    typeof payload.user_id === "string" &&
    typeof payload.knowledge_point_id === "string" &&
    typeof payload.title === "string" &&
    typeof payload.content_markdown === "string" &&
    (typeof payload.agent_draft_content === "string" || payload.agent_draft_content === null) &&
    typeof payload.is_user_edited === "boolean" &&
    typeof payload.updated_at === "string" &&
    typeof payload.language === "string" &&
    isRecord(payload.module) &&
    typeof payload.module.title === "string" &&
    isRecord(payload.course) &&
    typeof payload.course.title === "string" &&
    isRecord(payload.knowledge_point) &&
    typeof payload.knowledge_point.id === "string" &&
    typeof payload.knowledge_point.title === "string"
  );
}

function isRuntimeProfile(payload: unknown): payload is RuntimeProfile {
  return (
    isRecord(payload) &&
    typeof payload.id === "string" &&
    typeof payload.slug === "string" &&
    typeof payload.runtime_tier === "string" &&
    typeof payload.language === "string" &&
    typeof payload.runner === "string" &&
    typeof payload.timeout_ms === "number"
  );
}

function isLearningExercise(payload: unknown): payload is LearningExercise {
  return (
    isRecord(payload) &&
    typeof payload.id === "string" &&
    typeof payload.title === "string" &&
    typeof payload.prompt_markdown === "string" &&
    typeof payload.starter_code === "string" &&
    isRuntimeProfile(payload.runtime_profile) &&
    Array.isArray(payload.code_blanks) &&
    Array.isArray(payload.test_cases)
  );
}

function isTestResult(payload: unknown): payload is TestResult {
  return (
    isRecord(payload) &&
    typeof payload.case_id === "string" &&
    typeof payload.case_type === "string" &&
    typeof payload.passed === "boolean" &&
    typeof payload.weight === "number" &&
    typeof payload.duration_ms === "number" &&
    typeof payload.message === "string"
  );
}

function isCodeCompletionResult(payload: unknown): payload is CodeCompletionResult {
  return (
    isRecord(payload) &&
    typeof payload.result === "string" &&
    typeof payload.score === "number" &&
    isRecord(payload.score_breakdown) &&
    isRecord(payload.hard_gates) &&
    typeof payload.test_pass_rate === "number" &&
    typeof payload.feedback === "string" &&
    typeof payload.next_action === "string" &&
    typeof payload.fsrs_rating === "string"
  );
}

function isReviewStateSummary(payload: unknown): payload is ReviewStateSummary {
  return (
    isRecord(payload) &&
    typeof payload.knowledge_point_id === "string" &&
    typeof payload.card_state === "string" &&
    typeof payload.stability === "number" &&
    typeof payload.difficulty === "number" &&
    (typeof payload.due_at === "string" || payload.due_at === null) &&
    (typeof payload.last_review_at === "string" || payload.last_review_at === null) &&
    (typeof payload.last_attempt_id === "string" || payload.last_attempt_id === null) &&
    typeof payload.scheduled_days === "number" &&
    typeof payload.review_count === "number" &&
    typeof payload.lapse_count === "number" &&
    typeof payload.reps === "number" &&
    typeof payload.lapses === "number"
  );
}

function isRuntimeStatus(payload: unknown): payload is RuntimeStatus {
  return (
    payload === "success" ||
    payload === "missing_toolchain" ||
    payload === "unsupported" ||
    payload === "compile_error" ||
    payload === "runtime_error" ||
    payload === "timeout" ||
    payload === "test_failure"
  );
}

function toTutorConversationResponse(payload: unknown): TutorConversationResponse | null {
  if (!isRecord(payload) || typeof payload.conversation_id !== "string" || typeof payload.created !== "boolean" || typeof payload.idempotent_replayed !== "boolean") {
    return null;
  }
  return {
    conversation_id: payload.conversation_id,
    created: payload.created,
    idempotent_replayed: payload.idempotent_replayed,
  };
}

function toTutorInputAcceptedResponse(payload: unknown): TutorInputAcceptedResponse | null {
  if (!isRecord(payload) || typeof payload.conversation_id !== "string" || typeof payload.run_id !== "string" || typeof payload.input_revision !== "number" || typeof payload.message_id !== "string" || typeof payload.event_cursor !== "number" || typeof payload.merged !== "boolean" || typeof payload.input_replayed !== "boolean" || typeof payload.idempotent_replayed !== "boolean") {
    return null;
  }
  const run = toTutorRunState(payload.run);
  if (!run) return null;
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
  };
}

function toTutorRunState(payload: unknown): TutorRunState | null {
  if (!isRecord(payload) || typeof payload.run_id !== "string" || typeof payload.conversation_id !== "string" || (payload.origin !== "interactive" && payload.origin !== "proactive") || !isTutorRunStatus(payload.status) || typeof payload.input_revision !== "number" || typeof payload.cancelled !== "boolean" || typeof payload.iteration_count !== "number" || typeof payload.model_call_count !== "number" || typeof payload.capability_call_count !== "number" || typeof payload.effect_count !== "number" || !isNullableTutorTerminalOutcome(payload.terminal_outcome) || !isNullableString(payload.created_at) || !isNullableString(payload.updated_at)) {
    return null;
  }
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
    created_at: payload.created_at,
    updated_at: payload.updated_at,
  };
}

function toTutorActivityItem(payload: unknown): TutorActivityItem | null {
  if (!isRecord(payload) || typeof payload.activity_id !== "string" || typeof payload.category !== "string" || typeof payload.reason !== "string" || !isStringArray(payload.evidence) || !isNullableString(payload.created_at)) return null;
  return { activity_id: payload.activity_id, category: payload.category, reason: payload.reason, evidence: payload.evidence, created_at: payload.created_at };
}

function toTutorInboxItem(payload: unknown): TutorInboxItem | null {
  if (!isRecord(payload) || typeof payload.inbox_id !== "string" || typeof payload.activity_id !== "string" || typeof payload.message !== "string" || !isTutorInboxState(payload.state) || !isNullableString(payload.read_at) || !isNullableString(payload.dismissed_at) || !isNullableString(payload.created_at)) return null;
  return { inbox_id: payload.inbox_id, activity_id: payload.activity_id, message: payload.message, state: payload.state, read_at: payload.read_at, dismissed_at: payload.dismissed_at, created_at: payload.created_at };
}

function toTutorMemoryItem(payload: unknown): TutorMemoryItem | null {
  if (!isRecord(payload) || typeof payload.entry_id !== "string" || (payload.memory_kind !== "objective_fact" && payload.memory_kind !== "inference") || !isTutorMemoryState(payload.state) || typeof payload.category !== "string" || typeof payload.statement !== "string" || !isNullableString(payload.confidence) || typeof payload.provenance !== "string" || !isNullableString(payload.replaced_entry_id) || !isStringArray(payload.evidence) || !isNullableString(payload.retention_until) || !isNullableString(payload.stale_after) || !isNullableString(payload.created_at)) return null;
  return { entry_id: payload.entry_id, memory_kind: payload.memory_kind, state: payload.state, category: payload.category, statement: payload.statement, confidence: payload.confidence, provenance: payload.provenance, replaced_entry_id: payload.replaced_entry_id, evidence: payload.evidence, retention_until: payload.retention_until, stale_after: payload.stale_after, created_at: payload.created_at };
}

function toTutorPlanRevision(payload: unknown): TutorPlanRevision | null {
  if (!isRecord(payload) || typeof payload.revision_id !== "string" || !isNullableString(payload.predecessor_revision_id) || typeof payload.title !== "string" || !isStringArray(payload.outline) || !isStringArray(payload.diff) || typeof payload.learner_reason !== "string" || !isStringArray(payload.evidence) || !isNullableString(payload.created_at)) return null;
  return { revision_id: payload.revision_id, predecessor_revision_id: payload.predecessor_revision_id, title: payload.title, outline: payload.outline, diff: payload.diff, learner_reason: payload.learner_reason, evidence: payload.evidence, created_at: payload.created_at };
}

function toTutorPlanRevisionList(payload: unknown): TutorPlanRevisionList | null {
  if (!isRecord(payload) || !isNullableString(payload.active_revision_id) || !Array.isArray(payload.items)) return null;
  const items = payload.items.map(toTutorPlanRevision);
  if (items.some((item) => item === null)) return null;
  return { active_revision_id: payload.active_revision_id, items: items.filter((item): item is TutorPlanRevision => item !== null) };
}

function toTutorPreferences(payload: unknown): TutorPreferences | null {
  if (!isRecord(payload) || typeof payload.inferred_memory_enabled !== "boolean" || typeof payload.memory_setting_version !== "string" || typeof payload.proactive_paused !== "boolean" || typeof payload.proactive_enabled !== "boolean") return null;
  return { inferred_memory_enabled: payload.inferred_memory_enabled, memory_setting_version: payload.memory_setting_version, proactive_paused: payload.proactive_paused, proactive_enabled: payload.proactive_enabled };
}

function isTutorRunStatus(payload: unknown): payload is TutorRunState["status"] {
  return payload === "queued" || payload === "leased" || payload === "running" || payload === "waiting_for_input" || payload === "waiting_for_capability" || payload === "awaiting_effect_commit" || payload === "completed" || payload === "model_unavailable" || payload === "blocked_policy" || payload === "budget_exhausted" || payload === "cancelled" || payload === "failed";
}

function isNullableTutorTerminalOutcome(payload: unknown): payload is TutorRunState["terminal_outcome"] {
  return payload === null || payload === "completed" || payload === "model_unavailable" || payload === "blocked_policy" || payload === "budget_exhausted" || payload === "cancelled" || payload === "failed";
}

function isTutorInboxState(payload: unknown): payload is TutorInboxItem["state"] {
  return payload === "unread" || payload === "read" || payload === "dismissed";
}

function isTutorMemoryState(payload: unknown): payload is TutorMemoryItem["state"] {
  return payload === "active" || payload === "replaced" || payload === "deleted";
}

function isNullableString(payload: unknown): payload is string | null {
  return typeof payload === "string" || payload === null;
}

function isStringArray(payload: unknown): payload is string[] {
  return Array.isArray(payload) && payload.every((value) => typeof value === "string");
}

function isApiErrorEnvelope(payload: unknown): payload is { error: ApiError } {
  return isRecord(payload) && isRecord(payload.error) && typeof payload.error.code === "string";
}

function isForgetRisk(payload: unknown): payload is "low" | "normal" | "high" {
  return payload === "low" || payload === "normal" || payload === "high";
}

function isRecord(payload: unknown): payload is Record<string, unknown> {
  return typeof payload === "object" && payload !== null;
}

function isStringRecord(payload: unknown): payload is Record<string, string> {
  return isRecord(payload) && Object.values(payload).every((value) => typeof value === "string");
}

// --- SSE helpers ---

export function buildSSEUrl(path: string, params?: Record<string, string>): string {
  const url = new URL(path, API_BASE_URL);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      url.searchParams.set(key, value);
    }
  }
  return url.toString();
}

export function buildTutorRunEventsUrl(runId: string, userId: string): string {
  return buildSSEUrl(`/api/tutor/runs/${encodeURIComponent(runId)}/events`, { user_id: userId });
}

export function buildLearningMessageSSEUrl(sessionId: string): string {
  return buildSSEUrl(`/api/learning-sessions/${encodeURIComponent(sessionId)}/messages`);
}

export function buildOnboardingMessageSSEUrl(): string {
  return buildSSEUrl("/api/onboarding/messages");
}

export function buildReviewMessageSSEUrl(sessionId: string): string {
  return buildSSEUrl(`/api/reviews/${encodeURIComponent(sessionId)}/messages`);
}
