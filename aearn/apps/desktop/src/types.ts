export type ApiHealth = {
  status: "ok";
  service: string;
};

export type EnvironmentComponentStatus = "ready" | "missing" | "error" | "planned";
export type EnvironmentOverallStatus = "ready" | "needs_attention" | "blocked";
export type EnvironmentProductStatus = "executable" | "planned" | "static_review" | "unsupported";
export type EnvironmentGuidanceSeverity = "required" | "recommended" | "optional";

export type EnvironmentComponent = {
  component_id: string;
  label: string;
  kind: string;
  status: EnvironmentComponentStatus;
  version: string | null;
  executable_path: string | null;
  required_for: string[];
  guidance_id: string | null;
  message: string;
  diagnostic: {
    command: string | null;
    args: string[];
    exit_code: number | null;
    stdout: string;
    stderr: string;
  };
};

export type EnvironmentLanguageRunner = {
  language_id: string;
  display_name: string;
  runner_key: string;
  execution: string;
  capability_state: string;
  supports_execution: boolean;
  toolchain_status: EnvironmentComponentStatus;
  product_status: EnvironmentProductStatus;
  guidance_id: string | null;
  disclosure: string;
};

export type EnvironmentGuidance = {
  guidance_id: string;
  title: string;
  applies_to: string[];
  severity: EnvironmentGuidanceSeverity;
  summary: string;
  windows_steps: string[];
  verification_commands: string[];
  safety_notes: string[];
  source: "static_template";
};

export type EnvironmentDoctorReport = {
  generated_at: string;
  platform: {
    system: string;
    release: string;
    python_executable: string;
  };
  summary: {
    overall_status: EnvironmentOverallStatus;
    ready_count: number;
    missing_required_count: number;
    planned_runner_count: number;
  };
  components: EnvironmentComponent[];
  language_runners: EnvironmentLanguageRunner[];
  guidance: EnvironmentGuidance[];
};

export type RuntimeTier =
  | "browser_preview"
  | "python_stdout_test"
  | "node_typescript_test"
  | "sql_query_test"
  | "managed_compiled_test"
  | "compiled_sandbox_later";
export type LearningMode = "goal_based" | "material_based";
export type Language =
  | "javascript"
  | "python"
  | "typescript"
  | "sql"
  | "java"
  | "go"
  | "csharp"
  | "html_css";
export type RuntimeStatus =
  | "success"
  | "missing_toolchain"
  | "unsupported"
  | "compile_error"
  | "runtime_error"
  | "timeout"
  | "test_failure";
export type NextAction = "retry_same" | "show_hint" | "explain_error" | "review_variant" | "schedule_review" | "advance_next";
export type FsrsRating = "Again" | "Hard" | "Good" | "Easy";
export type ForgetRisk = "low" | "normal" | "high";
export type ExerciseType = "code_blank" | "fix_bug" | "implement_function" | "explain_code" | "review_ai_patch";
export type HintLevel = "nudge" | "concept" | "code_shape";
export type ExplanationFocus = "core_logic" | "boundary_condition" | "ai_generated_change";

export type RuntimeProfile = {
  id: string;
  slug: string;
  runtime_tier: RuntimeTier;
  language: Language;
  runner: "browser" | "python" | "node" | "sql" | "compiled" | "sandbox";
  supports_realtime_preview: boolean;
  supports_stdout: boolean;
  supports_tests: boolean;
  compile_required: boolean;
  timeout_ms: number;
  memory_limit_mb: number;
  sandbox_policy: Record<string, unknown>;
};

export type LanguageCourse = {
  id: string;
  slug: string;
  language: Language;
  title: string;
  description: string | null;
  level: "beginner" | "intermediate" | "advanced";
  runtime_profile_id: string;
  runtime_profile: RuntimeProfile;
  supported_exercise_types_json: string[];
};

export type UserProfile = {
  id: string;
  display_name: string;
  learning_style: string | null;
  teaching_preference: string | null;
  encouragement_preference: string | null;
  profession: string | null;
  background_context: string | null;
  preferred_time_slots: Record<string, unknown>[];
  reminder_preference: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type LocalUserListItem = UserProfile & {
  plan_count: number;
  active_plan_id: string | null;
  active_goal: string | null;
  last_activity_at: string | null;
};

export type LocalUserListResponse = {
  items: LocalUserListItem[];
  page_info: {
    limit: number;
    next_cursor: string | null;
    has_more: boolean;
  };
};

export type LocalUserDataSummary = {
  user: {
    id: string;
    display_name: string;
    created_at: string;
    updated_at: string;
  };
  counts: {
    active_plans: number;
    archived_or_deleted_plans: number;
    modules: number;
    knowledge_points: number;
    exercises: number;
    learning_sessions: number;
    attempts: number;
    review_states: number;
    review_logs: number;
    review_seed_banks: number;
    notes: number;
    onboarding_conversations: number;
    onboarding_messages: number;
    learning_messages: number;
    review_messages: number;
  };
  last_activity_at: string | null;
};

export type LocalUserResetResponse = {
  user: UserProfile;
  before_summary: LocalUserDataSummary;
  summary: LocalUserDataSummary;
  next_action: "return_to_onboarding";
};

export type LocalUserDeleteResponse = {
  deleted_user_id: string;
  before_summary: LocalUserDataSummary;
  next_action: "select_local_profile";
};

export type LocalUserExportPayload = {
  export_version: string;
  exported_at: string;
  user: LocalUserDataSummary["user"];
  preferences: Record<string, unknown>;
  summary: LocalUserDataSummary;
  plans: Record<string, unknown>[];
  modules: Record<string, unknown>[];
  knowledge_points: Record<string, unknown>[];
  learning_sessions: Record<string, unknown>[];
  attempt_summaries: Record<string, unknown>[];
  review_state_summaries: Record<string, unknown>[];
  review_log_summaries: Record<string, unknown>[];
  notes: Record<string, unknown>[];
  conversation_summaries: Record<string, unknown>;
  redaction: Record<string, string>;
};

export type DraftKnowledgePoint = {
  temp_id: string;
  title: string;
  description: string | null;
  skill_tags: string[];
  source: "template" | "user_material" | "agent_generated";
  exercise_refs: string[];
};

export type DraftModule = {
  temp_id: string;
  title: string;
  description: string | null;
  order_index: number;
  is_skippable: boolean;
  is_adjustable: boolean;
  estimated_sessions: number;
  source: "template" | "user_material" | "agent_generated";
  knowledge_points: DraftKnowledgePoint[];
};

export type PlanDraft = {
  draft_id: string;
  user_id: string;
  language_course_id: string;
  goal_text: string;
  language: Language;
  target_level: string;
  mode: LearningMode;
  deadline: string | null;
  modules: DraftModule[];
  runtime_boundary: {
    runtime_tier: RuntimeTier;
    unsupported_languages: string[];
    notice: string;
  };
  source_attribution: string[];
};

export type CreatedModule = {
  id: string;
  plan_id: string;
  title: string;
  description: string | null;
  order_index: number;
  status: "pending" | "in_progress" | "completed" | "skipped";
  is_skippable: boolean;
  is_adjustable: boolean;
  estimated_sessions: number;
};

export type CreatedKnowledgePointReviewStatePreview = {
  due_at: string | null;
  is_due: boolean;
  label: string;
};

export type CreatedKnowledgePoint = {
  id: string;
  module_id: string;
  language_course_id: string;
  title: string;
  description: string | null;
  order_index: number;
  skill_tags_json: string[];
  status: "pending" | "learning" | "reviewing" | "mastered";
  mastery_score: number;
  review_state?: CreatedKnowledgePointReviewStatePreview;
};

export type CreatedPlanResponse = {
  LearningPlan: {
    id: string;
    user_id: string;
    language_course_id: string;
    goal_text: string;
    language: Language;
    target_level: string;
    mode: LearningMode;
    deadline: string | null;
    status: "active" | "paused" | "completed" | "archived";
    overall_progress: number;
    current_module_id: string | null;
  };
  modules: CreatedModule[];
  knowledge_points: CreatedKnowledgePoint[];
  next_entry_point: {
    type: "learning_session";
    plan_id: string;
    knowledge_point_id: string | null;
  };
  idempotency_replayed?: boolean;
};

export type DashboardEntryPoint =
  | {
      type: "learning_session";
      plan_id: string;
      knowledge_point_id: string | null;
      next_action: NextAction;
    }
  | {
      type: "resume";
      plan_id: string;
      next_action: NextAction;
    }
  | {
      type: "review";
      plan_id: string;
      knowledge_point_id: string;
      next_action: NextAction;
    };

export type DashboardResponse = {
  active_goal: string;
  current_stage: string | null;
  current_language: Language;
  current_course: {
    id: string;
    title: string;
  };
  today_learning_tasks: Array<{
    type: "learning_session";
    plan_id: string;
    knowledge_point_id: string | null;
    title: string;
  }>;
  today_review_count: number;
  overall_progress: number;
  resume_available: boolean;
  next_entry_point: DashboardEntryPoint;
};

export type ResumeContextResponse = {
  last_session_summary: string | null;
  next_entry_point: {
    type: "learning_session";
    plan_id: string;
    knowledge_point_id: string | null;
    next_action: NextAction;
  };
  current_module: {
    id: string;
    title: string;
  } | null;
  current_stage: string | null;
  today_review_count: number;
  resume_available: boolean;
};

export type ApiError = {
  code: string;
  message: string;
  details: Record<string, unknown>;
  request_id: string;
  recoverable: boolean;
};

export type CodeBlank = {
  id: string;
  blank_key: string;
  placeholder: string;
  expected_concept: string;
  acceptable_patterns_json: Record<string, unknown>[];
  is_core: boolean;
  order_index: number;
};

export type ExerciseTestCase = {
  id: string;
  case_type: "visible" | "hidden" | "preview_assertion";
  input_json: Record<string, unknown>;
  expected_output_json: Record<string, unknown>;
  assertion_code: string | null;
  weight: number;
  is_critical: boolean;
  timeout_ms: number;
  order_index: number;
};

export type LearningExercise = {
  id: string;
  knowledge_point_id: string;
  runtime_profile_id: string;
  title: string;
  exercise_type: ExerciseType;
  prompt_markdown: string;
  starter_code: string;
  solution_reference: string | null;
  visible_test_policy: "visible_only" | "visible_and_hidden_summary" | "hidden_only";
  difficulty: number;
  estimated_minutes: number;
  requires_explanation: boolean;
  metadata_json: Record<string, unknown>;
  runtime_profile: RuntimeProfile;
  code_blanks: CodeBlank[];
  test_cases: ExerciseTestCase[];
};

export type LearningStage =
  | "documentation_reading"
  | "concept_intro"
  | "concept_check"
  | "concept_repair"
  | "practice_offer"
  | "concept_qna"
  | "readiness_check"
  | "practice_support";

export type LessonOutlineItem = {
  id: string;
  title: string;
  note: string;
};

export type LessonSource = {
  title: string;
  url: string;
};

export type LearningStageState = {
  covered_subpoint_ids?: string[];
  feynman_status?: "not_started" | "pending" | "passed" | "failed" | "legacy";
  practice_unlock_reason?:
    | "early_request"
    | "feynman_passed"
    | "legacy_session"
    | "concept_check_passed"
    | "concept_check_skipped"
    | "concept_check_repair_limit"
    | null;
  learning_incomplete?: boolean;
  concept_summary?: string;
  concept_check_attempts?: number;
  concept_check_result?: "correct" | "incorrect" | "unclear" | "skipped" | null;
  repair_limit_reached?: boolean;
};

export type LearningSessionInitialToolCall = {
  id: string;
  name: string;
  args: unknown;
  status: "done" | "running" | "error" | "pending";
};

export type LearningWorkbenchState = {
  exercise_id: string;
  source_attempt_id: string;
  source_attempt_type: "run" | "submit";
  code: string;
  filled_blanks: Record<string, string>;
  run_mode: "preview" | "visible_tests" | null;
};

export type LearningSessionResponse = {
  session_id: string;
  session_type: "learn";
  context_snapshot: {
    current_stage: string;
    LearningPlan: {
      id: string;
      current_module_id: string | null;
    };
    KnowledgePoint: {
      id: string;
      title: string;
      status: CreatedKnowledgePoint["status"];
    };
    RuntimeProfile: RuntimeProfile;
  };
  exercise: LearningExercise | null;
  lesson_outline: LessonOutlineItem[];
  lesson_sources: LessonSource[];
  learning_stage: LearningStage;
  learning_stage_state: LearningStageState;
  initial_agent_message: string;
  initial_tool_calls: LearningSessionInitialToolCall[];
  latest_run?: RunExerciseResponse | null;
  latest_submit?: SubmitExerciseResponse | null;
  latest_workbench_state?: LearningWorkbenchState | null;
  session_state: "learning";
};

export type DocumentationCodeBlock = {
  language: string;
  code: string;
  caption: string;
  source_type?: "official" | "trusted" | "aearn" | string | null;
};

export type DocumentationSection = {
  id: "official_documentation" | "examples" | string;
  type: string;
  title: string;
  content_markdown: string;
  code_blocks: DocumentationCodeBlock[];
};

export type DocumentationReference = {
  title: string;
  url: string;
  source_type?: "official" | "trusted" | "aearn" | string | null;
  retrieved_at?: string | null;
};

export type KnowledgePointDocumentationResponse = {
  knowledge_point_id: string;
  title: string;
  summary: string;
  sections: DocumentationSection[];
  references: DocumentationReference[];
  generated_at: string;
  cache_hit: boolean;
};

export type TriggerConceptCheckResponse = {
  session_id: string;
  learning_stage: "concept_check";
  learning_stage_state: LearningStageState;
  agent_message: string;
  tool_call: LearningSessionInitialToolCall;
};

export type LearningHistoryResponse = {
  knowledge_point_id: string;
  knowledge_point_title: string;
  active_session_id: string | null;
  sessions: Array<{
    session_id: string;
    is_active: boolean;
    status: string;
    started_at: string | null;
    messages: Array<{
      id: string;
      role: "user" | "agent";
      content: string;
      tool_calls?: LearningSessionInitialToolCall[];
      created_at: string | null;
    }>;
  }>;
};

export type TestResult = {
  case_id: string;
  case_type: "visible" | "hidden" | "preview_assertion";
  passed: boolean;
  weight: number;
  is_critical: boolean;
  duration_ms: number;
  message: string;
};

export type RunExerciseResponse = {
  attempt_id: string;
  attempt_type: "run";
  runtime_status: RuntimeStatus;
  preview_html: string | null;
  stdout: string;
  stderr: string;
  test_pass_rate: number;
  passed_test_count: number;
  total_test_count: number;
  test_results: TestResult[];
  error_message: string | null;
  next_action: NextAction;
  idempotency_replayed?: boolean;
};

export type CodeCompletionResult = {
  result: "failed" | "partial" | "passed" | "easy";
  score: number;
  score_breakdown: Record<string, number>;
  hard_gates: {
    runtime_gate: boolean;
    test_gate: boolean;
    core_blank_gate: boolean;
    explanation_gate: boolean;
  };
  test_pass_rate: number;
  hint_usage_count: number;
  error_count: number;
  weak_points: string[];
  error_cause: string | null;
  feedback: string;
  next_action: NextAction;
  fsrs_rating: FsrsRating;
  review_ai_patch_result?: {
    verdict: "pass" | "fail" | "uncertain";
    expected_verdict: "pass" | "fail" | "uncertain";
    evidence_quality: "strong" | "weak";
    expected_risk: string;
    learner_next_action: "accept" | "reject" | "request_change" | "run_more_tests";
  };
};

export type ReviewStateSummary = {
  knowledge_point_id: string;
  card_state: "new" | "learning" | "review" | "relearning";
  stability: number;
  difficulty: number;
  due_at: string | null;
  last_review_at: string | null;
  last_attempt_id: string | null;
  last_fsrs_rating: FsrsRating | null;
  scheduled_days: number;
  review_count: number;
  lapse_count: number;
  reps: number;
  lapses: number;
  scheduler_version?: string | null;
};

export type SubmitExerciseResponse = {
  attempt_id: string;
  code_completion_result: CodeCompletionResult;
  KnowledgePoint: {
    id: string;
    status: CreatedKnowledgePoint["status"];
    mastery_score: number;
    last_exercise_result: "failed" | "partial" | "passed" | "easy" | null;
    last_exercise_score: number | null;
  };
  ReviewState: ReviewStateSummary;
  next_action: NextAction;
  idempotency_replayed?: boolean;
};

export type HintResponse = {
  hint: {
    hint_level: HintLevel;
    content: string;
  };
  hint_usage_count: number;
  affected_score: {
    max_result: "passed" | "easy";
    score_penalty_hint: number;
  };
  next_action: NextAction;
  idempotency_replayed?: boolean;
};

export type ExplainErrorResponse = {
  error_cause: string;
  explanation: string;
  fix_suggestion: string;
  related_knowledge_points: Array<{
    id: string;
    title: string;
  }>;
  next_action: NextAction;
  generation_source?: "llm" | "deterministic";
  generation_model?: string;
  idempotency_replayed?: boolean;
};

export type ExplanationCheckResponse = {
  result: "passed" | "partial" | "failed";
  score: number;
  score_breakdown: {
    explanation_check: number;
  };
  follow_up_required: boolean;
  feedback: string;
  next_action: NextAction;
  idempotency_replayed?: boolean;
};

export type ReviewDueItem = {
  ReviewState: ReviewStateSummary;
  KnowledgePoint: {
    id: string;
    title: string;
    status: CreatedKnowledgePoint["status"];
    mastery_score: number;
    weak_points_json: string[];
  };
  forget_risk: ForgetRisk;
};

export type TodayReviewsResponse = {
  items: ReviewDueItem[];
  page_info: {
    limit: number;
    next_cursor: string | null;
    has_more: boolean;
  };
  timezone: "Asia/Shanghai";
  generated_at: string;
};

export type ReviewSessionResponse = {
  session_id: string;
  session_type: "review";
  knowledge_point: {
    id: string;
    title: string;
    status: CreatedKnowledgePoint["status"];
    weak_points_json: string[];
  };
  review_exercise: LearningExercise;
  ReviewState: ReviewStateSummary;
  review_stage: ReviewStage;
  review_stage_state: ReviewStageState;
  current_node: ReviewCurrentNode;
  warmup: ReviewWarmupState;
  selected_seed_id: string | null;
  seed_bank?: {
    id: string;
    status: "generating" | "ready" | "failed";
    generator_version: string;
    seed_count: number;
    generated_at: string | null;
    quality_report: Record<string, unknown>;
  };
  variant_reason: string;
  initial_agent_message: string;
};

export type ReviewStage = "warmup" | "warmup_repair" | "variant_practice" | "exercise" | "exercise_feedback" | "final_summary" | "submitted";

export type ReviewCurrentNode =
  | {
      type: "warmup" | "warmup_repair";
      stage: ReviewStage;
      can_pause: boolean;
      warmup: ReviewWarmupState;
      position: number;
      target_count: number;
    }
  | {
      type: "exercise";
      stage: "exercise";
      can_pause: boolean;
      exercise: LearningExercise;
      position: number;
      target_count: number;
      completed_count: number;
      candidate_id: string;
    }
  | {
      type: "final_summary";
      stage: ReviewStage;
      can_pause: boolean;
      finalization: Record<string, unknown>;
      completed_count: number;
      target_count: number;
    };

export type ReviewWarmupState = {
  question: string;
  expected_focus: string;
  result: "pending" | "correct" | "incorrect" | "unclear" | "skipped";
  repair_count: number;
  last_answer: string | null;
  feedback: string | null;
  recall_level?: "clear" | "fuzzy" | "wrong" | "skipped" | null;
  diagnosis?: Record<string, unknown>;
};

export type ReviewStageState = {
  review_stage: ReviewSessionResponse["review_stage"];
  knowledge_point_id: string;
  seed_bank_id: string;
  seed_id: string;
  warmup: ReviewWarmupState;
  variant: {
    exercise_id: string;
    exercise_type: ExerciseType;
    guided: boolean;
    selection_reason: string;
  };
};

export type ReviewWarmupResultResponse = {
  session_id: string;
  review_stage: ReviewSessionResponse["review_stage"];
  warmup: ReviewWarmupState;
  review_stage_state: ReviewStageState;
  current_node: ReviewCurrentNode;
  next_action: "start_variant" | "start_exercise" | "retry_same";
};

export type ReviewAiPatchAnswer = {
  verdict: "pass" | "fail" | "uncertain";
  evidence: string;
  knowledge_point_risk: string;
  next_action: "accept" | "reject" | "request_change" | "run_more_tests";
};

export type ReviewExerciseResultResponse = {
  attempt_id?: string;
  result: CodeCompletionResult["result"];
  score: number;
  score_breakdown: CodeCompletionResult["score_breakdown"];
  hard_gates?: CodeCompletionResult["hard_gates"];
  test_pass_rate?: number;
  hint_usage_count?: number;
  error_count?: number;
  fsrs_rating: FsrsRating;
  weak_points: string[];
  error_cause?: string | null;
  feedback: string;
  code_completion_result: CodeCompletionResult;
  next_action: NextAction | "next_exercise";
  review_stage?: ReviewStage;
  review_stage_state?: ReviewStageState;
  current_node?: ReviewCurrentNode;
  review_exercise?: LearningExercise;
  final_result?: {
    final_fsrs_rating: FsrsRating;
    aggregate_result: Record<string, unknown>;
    due_at: string | null;
    forget_risk: ForgetRisk;
  } | null;
  due_at?: string | null;
  forget_risk?: ForgetRisk;
  ReviewState?: ReviewStateSummary;
  KnowledgePoint?: SubmitExerciseResponse["KnowledgePoint"];
  judgement_ready?: boolean;
  judgement_blocking_fields?: string[];
  clarification_question?: string;
  idempotency_replayed?: boolean;
};

export type ReviewHistoryMessage = {
  id: string;
  role: "user" | "agent";
  content: string;
  client_message_id: string | null;
  created_at: string | null;
};

export type ReviewMessagesResponse = {
  session_id: string;
  messages: ReviewHistoryMessage[];
};

export type UserPreferencesUpdate = {
  display_name?: string;
  learning_style?: string | null;
  teaching_preference?: string | null;
  encouragement_preference?: string | null;
  profession?: string | null;
  background_context?: string | null;
  preferred_time_slots?: Record<string, unknown>[];
  reminder_preference?: Record<string, unknown>;
};

export type NoteRecord = {
  id: string;
  user_id: string;
  knowledge_point_id: string;
  title: string;
  content_markdown: string;
  agent_draft_content: string | null;
  is_user_edited: boolean;
  updated_at: string;
  language: Language;
  plan_id: string;
  course: {
    id: string;
    title: string;
  };
  module: {
    id: string;
    title: string;
  };
  knowledge_point: {
    id: string;
    title: string;
    description: string | null;
  };
};

export type NoteListResponse = {
  items: NoteRecord[];
  page_info: {
    limit: number;
    next_cursor: string | null;
    has_more: boolean;
  };
};

export class ApiRequestError extends Error {
  readonly apiError: ApiError;

  constructor(apiError: ApiError) {
    super(`${apiError.code}: ${apiError.message}`);
    this.apiError = apiError;
  }
}
