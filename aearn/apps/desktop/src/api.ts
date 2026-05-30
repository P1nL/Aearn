import type {
  ApiError,
  ApiHealth,
  CodeCompletionResult,
  CreatedPlanResponse,
  DashboardResponse,
  ExplainErrorResponse,
  ExplanationFocus,
  ExplanationCheckResponse,
  HintLevel,
  HintResponse,
  Language,
  LanguageCourse,
  LearningExercise,
  LearningHistoryResponse,
  LearningMode,
  LearningSessionResponse,
  NoteListResponse,
  NoteRecord,
  PlanDraft,
  ReviewDueItem,
  ReviewAiPatchAnswer,
  ReviewExerciseResultResponse,
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
  UserPreferencesUpdate,
  UserProfile,
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

export async function fetchPlanDetail(planId: string, signal?: AbortSignal): Promise<CreatedPlanResponse> {
  const payload = await requestJson(`${API_BASE_URL}/api/plans/${encodeURIComponent(planId)}`, { signal });
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

export async function submitReviewWarmupResult(input: {
  sessionId: string;
  action: "answer" | "skip";
  answer?: string;
}): Promise<ReviewWarmupResultResponse> {
  const payload = await requestJson(`${API_BASE_URL}/api/reviews/${input.sessionId}/warmup-result`, {
    method: "POST",
    body: JSON.stringify({
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
  sessionId: string;
  exerciseId: string;
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
      exercise_id: input.exerciseId,
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
  title?: string;
  contentMarkdown?: string;
  isUserEdited?: boolean;
}): Promise<NoteRecord> {
  const payload = await requestJson(`${API_BASE_URL}/api/notes/${input.noteId}`, {
    method: "PATCH",
    body: JSON.stringify({
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
    Array.isArray(payload.modules) &&
    Array.isArray(payload.knowledge_points) &&
    isRecord(payload.next_entry_point)
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
    typeof payload.initial_agent_message === "string"
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
            typeof message.content === "string",
        ),
    )
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
    payload.next_action === "start_variant"
  );
}

function isReviewWarmupState(payload: unknown): payload is ReviewWarmupResultResponse["warmup"] {
  return (
    isRecord(payload) &&
    typeof payload.question === "string" &&
    typeof payload.expected_focus === "string" &&
    typeof payload.result === "string" &&
    typeof payload.repair_count === "number" &&
    (typeof payload.last_answer === "string" || payload.last_answer === null) &&
    (typeof payload.feedback === "string" || payload.feedback === null)
  );
}

function isReviewExerciseResultResponse(payload: unknown): payload is ReviewExerciseResultResponse {
  return (
    isRecord(payload) &&
    typeof payload.attempt_id === "string" &&
    typeof payload.result === "string" &&
    typeof payload.score === "number" &&
    isRecord(payload.score_breakdown) &&
    typeof payload.fsrs_rating === "string" &&
    Array.isArray(payload.weak_points) &&
    typeof payload.feedback === "string" &&
    (typeof payload.due_at === "string" || payload.due_at === null) &&
    isForgetRisk(payload.forget_risk) &&
    isReviewStateSummary(payload.ReviewState) &&
    isRecord(payload.KnowledgePoint) &&
    typeof payload.KnowledgePoint.id === "string" &&
    isCodeCompletionResult(payload.code_completion_result) &&
    typeof payload.next_action === "string"
  );
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
  return payload === "success" || payload === "runtime_error" || payload === "timeout" || payload === "unsupported";
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

export function buildLearningMessageSSEUrl(sessionId: string): string {
  return buildSSEUrl(`/api/learning-sessions/${encodeURIComponent(sessionId)}/messages`);
}

export function buildOnboardingMessageSSEUrl(): string {
  return buildSSEUrl("/api/onboarding/messages");
}

export function buildReviewMessageSSEUrl(sessionId: string): string {
  return buildSSEUrl(`/api/reviews/${encodeURIComponent(sessionId)}/messages`);
}
